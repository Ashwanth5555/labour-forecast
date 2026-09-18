"""The three application logins, seeded on startup.

Seeding is idempotent and insert-only: a username that already exists is left
completely alone, so a password changed later in the database is never quietly
reset back to the demo value on the next restart.

These are demo credentials for a local POC. They are documented in README.md,
and anything beyond a local run should replace them - see
`scripts/seed_users.py` for rotating a password.
"""
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.security import hash_password
from app.models import AppUser

DEMO_USERS = [
    {"username": "admin", "password": "Admin@2026", "full_name": "Alex Nguyen", "role": "ADMIN"},
    {"username": "manager", "password": "Manager@2026", "full_name": "Maya Patel", "role": "LOCATION_MANAGER"},
    {"username": "analyst", "password": "Analyst@2026", "full_name": "Dana Singh", "role": "DATA_ANALYST"},
]


def ensure_demo_users(db: Session) -> list[str]:
    """Creates any of the three logins that are missing. Returns the usernames
    actually created, so startup can log what it did without implying it
    rewrote accounts that were already there."""
    existing = set(db.execute(select(AppUser.username)).scalars().all())
    created = []
    for user in DEMO_USERS:
        if user["username"] in existing:
            continue
        db.add(AppUser(
            username=user["username"],
            password_hash=hash_password(user["password"]),
            full_name=user["full_name"],
            role=user["role"],
        ))
        created.append(user["username"])
    if created:
        db.commit()
    return created
