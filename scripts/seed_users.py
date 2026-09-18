"""Create the application logins, or reset one password.

The backend already seeds any missing login on startup, so this script is only
needed to rotate a password.

    # create anything missing (same as a backend restart)
    python scripts/seed_users.py

    # set a new password for one account
    python scripts/seed_users.py --username admin --password "NewPassw0rd!"

Run it from the repository root with the project venv:
    ../.venv/Scripts/python.exe scripts/seed_users.py
"""
import argparse
import sys
from pathlib import Path

# The application package lives in backend_sodexo. This previously pointed at a
# "backend" directory that no longer exists, so the script could not import
# anything at all.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend_sodexo"))

from sqlalchemy import select  # noqa: E402

from app.core.database import Base, SessionLocal, engine  # noqa: E402
from app.core.security import hash_password  # noqa: E402
from app.core.users import DEMO_USERS, ensure_demo_users  # noqa: E402
import app.models  # noqa: E402, F401
from app.models import AppUser  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--username", help="Account to set a new password for.")
    parser.add_argument("--password", help="The new password. Required with --username.")
    args = parser.parse_args()

    if bool(args.username) != bool(args.password):
        parser.error("--username and --password must be given together.")

    Base.metadata.create_all(engine)
    db = SessionLocal()
    try:
        if args.username:
            username = args.username.strip().lower()
            user = db.execute(select(AppUser).where(AppUser.username == username)).scalar_one_or_none()
            if user is None:
                known = ", ".join(u["username"] for u in DEMO_USERS)
                print(f"No such user: {username}. Seeded accounts are: {known}")
                return 1
            user.password_hash = hash_password(args.password)
            db.commit()
            print(f"Password updated for {username}.")
            return 0

        created = ensure_demo_users(db)
        print(f"Created: {', '.join(created)}" if created else "All logins already exist - nothing to do.")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
