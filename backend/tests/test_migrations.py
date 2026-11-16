"""Migrations against real databases, both starting points:

- empty database -> head
- a v1 database (created by v1's create_all, never migrated, with data) -> head

The second is what production looked like on the first Alembic deploy, which
failed with `relation "users" already exists`. Each case gets its own
throwaway database next to the test database.
"""

import os
import subprocess
import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

BACKEND = Path(__file__).resolve().parent.parent
V1_SCHEMA = Path(__file__).resolve().parent / "fixtures" / "v1_schema.sql"
TEST_URL = make_url(os.environ["DATABASE_URL"])


@pytest.fixture
def scratch_db(request):
    name = f"loopwire_mig_{request.node.name.removeprefix('test_')}"[:60]
    admin = create_engine(TEST_URL.set(database="postgres"), isolation_level="AUTOCOMMIT")
    with admin.connect() as c:
        c.execute(text(f'DROP DATABASE IF EXISTS "{name}"'))
        c.execute(text(f'CREATE DATABASE "{name}"'))
    url = TEST_URL.set(database=name)
    engine = create_engine(url)
    yield url, engine
    engine.dispose()
    with admin.connect() as c:
        c.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
    admin.dispose()


def alembic(url, *args: str) -> subprocess.CompletedProcess:
    env = {**os.environ, "DATABASE_URL": url.render_as_string(hide_password=False)}
    return subprocess.run([sys.executable, "-m", "alembic", *args], cwd=BACKEND, env=env, capture_output=True, text=True)


def assert_at_head_without_drift(url):
    upgrade = alembic(url, "upgrade", "head")
    assert upgrade.returncode == 0, upgrade.stderr
    check = alembic(url, "check")
    assert check.returncode == 0, check.stdout + check.stderr


def test_empty_database(scratch_db):
    url, _ = scratch_db
    assert_at_head_without_drift(url)


def test_v1_database_upgrades_in_place(scratch_db):
    url, engine = scratch_db
    long_text = " ".join(["word"] * 2380)
    with engine.begin() as c:
        c.exec_driver_sql(V1_SCHEMA.read_text())
        c.execute(text("INSERT INTO users (id, email, google_id, telegram_chat_id) VALUES "
                       "(1, 'a@example.com', 'g1', 111), (2, 'b@example.com', 'g2', NULL)"))
        c.execute(text("INSERT INTO loopwire_sends (id, user_id, period, item_count, email_sent) "
                       "VALUES (1, 1, 'daily', 3, true)"))
        c.execute(text(
            "INSERT INTO saved_items (id, user_id, url, type, status, clean_text, estimated_read_time_minutes, "
            "loopwire_send_id) VALUES "
            "(1, 1, 'https://example.com/post?utm_source=x', 'article', 'summarized', :t, 15, 1), "
            "(2, 1, 'https://example.com/post', 'article', 'summarized', 'short text', 3, 1), "
            "(3, 1, 'https://www.youtube.com/watch?v=abc', 'youtube', 'summarized', 'a transcript', 12, 1), "
            "(4, 2, 'https://example.com/post', 'article', 'pending', NULL, NULL, NULL)"), {"t": long_text})
        c.execute(text("INSERT INTO engagement_events (user_id, item_id, event_type) VALUES "
                       "(1, 1, 'opened'), (1, 1, 'opened'), (1, 1, 'clicked_source'), (1, 1, 'clicked_source'), "
                       "(1, 2, 'opened'), (1, 2, 'skipped')"))

    assert_at_head_without_drift(url)

    with engine.connect() as c:
        items = {r.id: r for r in c.execute(text(
            "SELECT id, canonical_url, word_count, estimated_read_time_minutes FROM saved_items"))}
        events = c.execute(text("SELECT item_id, event_type FROM engagement_events")).all()
        users = c.execute(text("SELECT count(*) FROM users WHERE recall_enabled")).scalar()

    # every row survives; the later duplicate is kept but can't collide with the original
    assert len(items) == 4 and users == 2
    assert items[1].canonical_url == "https://example.com/post"
    assert items[2].canonical_url == "https://example.com/post#loopwire-duplicate-2"
    assert items[4].canonical_url == "https://example.com/post"  # another user's copy is untouched
    # read time recomputed from the real word count; YouTube keeps v1's value (no duration stored)
    assert (items[1].word_count, items[1].estimated_read_time_minutes) == (2380, 10)
    assert items[3].estimated_read_time_minutes == 12
    # v1 "opened"/"skipped" are noise under v2 semantics; clicks are kept once
    assert events == [(1, "clicked_source")]


def test_v2_database_is_left_alone(scratch_db):
    url, engine = scratch_db
    assert_at_head_without_drift(url)
    with engine.begin() as c:
        c.execute(text("INSERT INTO users (email, google_id) VALUES ('a@example.com', 'g1')"))
    assert_at_head_without_drift(url)  # re-running on deploy is a no-op
    with engine.connect() as c:
        assert c.execute(text("SELECT count(*) FROM users")).scalar() == 1
