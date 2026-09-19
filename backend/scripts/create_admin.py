"""One-shot script to create the first admin user for an organization
(DECISIONS.md, 2026-09-19).

No signup UI exists by design — this is an invite-only, staff-managed
system, and building one for a system that will only ever have accounts
created by an admin is unnecessary surface area. Run this once per
environment after `alembic upgrade head` has applied migration 0001
(which creates the pilot organization).

Usage (from backend/, with the environment's real DATABASE_URL already
active — via .env locally, or the real env vars in production):

    python -m scripts.create_admin --email admin@example.com

Prompts for the password interactively (never as a CLI argument) so it
never appears in shell history or a process listing. Pass --org-id to
attach the new user to a specific organization; otherwise, if exactly one
Organization row exists (the common case — the pilot org migration 0001
creates), it's used automatically.
"""

import argparse
import asyncio
import getpass
import sys

from sqlalchemy import select

from app.auth import hash_password
from app.database import AsyncSessionLocal
from app.models.db_models import Organization, User


async def _resolve_org_id(session, org_id: str | None) -> str:
    if org_id:
        return org_id
    result = await session.execute(select(Organization))
    orgs = result.scalars().all()
    if len(orgs) == 1:
        return orgs[0].id
    if not orgs:
        print(
            "No organizations exist yet — run `alembic upgrade head` first "
            "(migration 0001 creates the pilot organization).",
            file=sys.stderr,
        )
        sys.exit(1)
    print("Multiple organizations exist — pass --org-id to choose one:", file=sys.stderr)
    for org in orgs:
        print(f"  {org.id}  {org.name}", file=sys.stderr)
    sys.exit(1)


async def _create_admin(email: str, org_id_arg: str | None, role: str) -> None:
    password = getpass.getpass("Password: ")
    confirm = getpass.getpass("Confirm password: ")
    if password != confirm:
        print("Passwords did not match.", file=sys.stderr)
        sys.exit(1)
    if len(password) < 8:
        print("Password must be at least 8 characters.", file=sys.stderr)
        sys.exit(1)

    async with AsyncSessionLocal() as session:
        org_id = await _resolve_org_id(session, org_id_arg)

        existing = await session.execute(select(User).where(User.email == email))
        if existing.scalar_one_or_none() is not None:
            print(f"A user with email {email!r} already exists.", file=sys.stderr)
            sys.exit(1)

        user = User(
            org_id=org_id,
            email=email,
            password_hash=hash_password(password),
            role=role,
        )
        session.add(user)
        await session.commit()
        print(f"Created user {email!r} (role={role!r}) in org {org_id}.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Create the first admin user for an organization.")
    parser.add_argument("--email", required=True)
    parser.add_argument(
        "--org-id", default=None,
        help="Organization id; auto-detected if exactly one organization exists",
    )
    parser.add_argument("--role", default="admin")
    args = parser.parse_args()
    asyncio.run(_create_admin(args.email, args.org_id, args.role))


if __name__ == "__main__":
    main()
