"""
Bootstrap script — create the first super_admin user.

Usage:
    python scripts/create_superadmin.py
    python scripts/create_superadmin.py --username admin --password secret

The script prompts for username and password if they are not supplied as
arguments.  It exits with a non-zero code if the username is already taken.
"""

import argparse
import getpass
import os
import sys
from pathlib import Path

# Make sure the project root is on sys.path when the script is run directly.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# Ensure settings can always load .env regardless of current working directory.
os.chdir(PROJECT_ROOT)


def main() -> None:
    """
    Parse arguments, validate input, and insert the super_admin row.
    """
    from sqlalchemy import create_engine, select
    from sqlalchemy.orm import sessionmaker

    from app.core.config import settings
    from app.core.security import get_password_hash
    from app.db.models import User, UserRole

    parser = argparse.ArgumentParser(description="Create a super_admin user.")
    parser.add_argument("--username", help="Login username for the super_admin account.")
    parser.add_argument("--password", help="Plain-text password (will be hashed).")
    args = parser.parse_args()

    username = args.username or input("Username: ").strip()
    if not username:
        print("ERROR: username cannot be empty.", file=sys.stderr)
        sys.exit(1)

    password = args.password or getpass.getpass("Password: ")
    if len(password) < 8:
        print("ERROR: password must be at least 8 characters.", file=sys.stderr)
        sys.exit(1)

    engine = create_engine(settings.DATABASE_URL_SYNC)
    Session = sessionmaker(bind=engine)

    with Session() as session:
        existing = session.execute(select(User).filter(User.username == username)).scalar_one_or_none()
        if existing:
            print(f"ERROR: username '{username}' is already taken.", file=sys.stderr)
            sys.exit(1)

        user = User(
            username=username,
            hashed_password=get_password_hash(password),
            role=UserRole.SUPER_ADMIN,
            company_id=None,
        )
        session.add(user)
        session.commit()
        session.refresh(user)

    print(f"super_admin created — id: {user.id}  username: {user.username}")


if __name__ == "__main__":
    main()
