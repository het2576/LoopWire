"""Bring the database schema up to date (Alembic migrations).

    uv run python -m app.init_db            # upgrade to latest (safe, non-destructive)
    uv run python -m app.init_db --reset    # drop everything first (local dev only)

v1 dropped and recreated every table on each run; schema changes now go
through migrations/ so a deploy never wipes data.
"""

import sys
from pathlib import Path

from alembic import command
from alembic.config import Config

from app import models  # noqa: F401
from app.db import Base, engine

ALEMBIC_INI = Path(__file__).resolve().parent.parent / "alembic.ini"


def main() -> None:
    cfg = Config(str(ALEMBIC_INI))
    if "--reset" in sys.argv:
        with engine.begin() as conn:
            Base.metadata.drop_all(bind=conn)
            conn.exec_driver_sql("DROP TABLE IF EXISTS alembic_version")
        print("Dropped all tables.")
    command.upgrade(cfg, "head")
    print("Schema is at the latest migration.")


if __name__ == "__main__":
    main()
