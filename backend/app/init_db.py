"""Drops and recreates every table for the multi-tenant schema (Phase A,
prdv2.md). Per-user interest profiles now live on the `users` table, seeded
blank - there's no more global default to seed.

This is destructive by design for this migration (the old single-user
schema's data doesn't carry over cleanly to a required user_id FK) - only
run this if you've already decided to start the multi-tenant schema fresh.

Run with: uv run python -m app.init_db
"""

from app import models  # noqa: F401  (ensures models are registered on Base.metadata)
from app.db import Base, engine


def main() -> None:
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    print("Dropped old schema and created the multi-tenant schema (users, connection_codes, "
          "saved_items, loopwire_sends, engagement_events). No seed data - sign in to create your first user.")


if __name__ == "__main__":
    main()
