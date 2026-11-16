"""Test harness: real Postgres (throwaway test DB), no network, no LLM.

Settings and the SQLAlchemy engine are created at import time, so the env is
pinned here before any `app.*` import.
"""

import os

os.environ["DATABASE_URL"] = os.environ.get(
    "TEST_DATABASE_URL", "postgresql+psycopg2://postgres@localhost:54329/loopwire_test"
)
os.environ["GEMINI_API_KEY"] = ""  # any accidental live LLM call fails loudly
os.environ["INTERNAL_AUTH_SECRET"] = "test-internal-secret"
os.environ["TRACKING_SIGNING_SECRET"] = "test-tracking-secret"
os.environ["SEND_LOOPWIRE_SECRET"] = "test-send-secret"
os.environ["PROCESS_PENDING_SECRET"] = "test-process-secret"
os.environ["TELEGRAM_BOT_TOKEN"] = ""
os.environ["RESEND_API_KEY"] = ""
os.environ["BACKEND_BASE_URL"] = "https://api.test"
os.environ["DASHBOARD_BASE_URL"] = "https://app.test"

import itertools

import numpy as np
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app import models
from app.db import Base, SessionLocal, engine

_TABLES = ", ".join(t.name for t in reversed(Base.metadata.sorted_tables))


@pytest.fixture(scope="session", autouse=True)
def _schema():
    with engine.begin() as conn:
        Base.metadata.drop_all(bind=conn)
        Base.metadata.create_all(bind=conn)
    yield


@pytest.fixture(autouse=True)
def _clean_tables():
    yield
    with engine.begin() as conn:
        conn.execute(text(f"TRUNCATE {_TABLES} RESTART IDENTITY CASCADE"))


@pytest.fixture
def db():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def client():
    from app.main import app

    with TestClient(app) as c:
        yield c


_ids = itertools.count(1)


@pytest.fixture
def make_user(db):
    def _make(email: str | None = None, profile: str | None = None, chat_id: int | None = None) -> models.User:
        n = next(_ids)
        user = models.User(email=email or f"user{n}@example.com", google_id=f"g-{n}",
                           interest_profile_text=profile, telegram_chat_id=chat_id)
        db.add(user)
        db.commit()
        db.refresh(user)
        return user

    return _make


def topic_vec(topic: int, noise: float = 0.0, seed: int = 0, dims: int = 768) -> list[float]:
    """Deterministic fake embedding: a unit spike on one axis per topic."""
    v = np.zeros(dims)
    v[topic] = 1.0
    if noise:
        v += np.random.default_rng(seed).normal(0, noise, dims)
    return (v / np.linalg.norm(v)).tolist()


@pytest.fixture
def make_item(db):
    def _make(user: models.User, *, url: str | None = None, status: str = models.STATUS_SUMMARIZED,
              topic: int | None = None, title: str | None = None, **kw) -> models.SavedItem:
        n = next(_ids)
        url = url or f"https://example.com/post-{n}"
        item = models.SavedItem(
            user_id=user.id, url=url, canonical_url=kw.pop("canonical_url", url), type=kw.pop("type", "article"),
            status=status, title=title or f"Item {n}",
            summary=kw.pop("summary", f"Summary {n}" if status == models.STATUS_SUMMARIZED else None),
            embedding=topic_vec(topic) if topic is not None else kw.pop("embedding", None), **kw,
        )
        db.add(item)
        db.commit()
        db.refresh(item)
        return item

    return _make


def auth_headers(user: models.User) -> dict[str, str]:
    return {"X-Internal-Secret": "test-internal-secret", "X-User-Id": str(user.id)}
