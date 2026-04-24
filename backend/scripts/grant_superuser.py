"""
Grant superuser rights on a deployed database — or create a fresh superuser
account if none exists for the target email.

Credentials are read from environment variables or interactive prompts. Nothing
is ever taken from command-line arguments (which would leak into shell history
and `ps` output) and nothing is committed to the repo.

Usage (from an already-authenticated shell on the deploy host):

    # promote an existing account
    docker compose -f deploy/docker/docker-compose.prod.yml exec backend \\
        python -m scripts.grant_superuser --email alice@example.com

    # create + promote a brand-new account (prompts for password etc.)
    docker compose -f deploy/docker/docker-compose.prod.yml exec backend \\
        python -m scripts.grant_superuser --email alice@example.com --create

You can skip the prompts by exporting env vars before the call:

    export SUPERUSER_PASSWORD=...
    export SUPERUSER_NAME="Alice Smith"
    export SUPERUSER_OPENREVIEW_ID="~Alice_Smith1"

The password is never echoed and never stored in plaintext — it is hashed with
the same `hash_password` the signup endpoint uses.
"""
import argparse
import asyncio
import getpass
import os
import sys

from sqlalchemy import select

from app.db.session import AsyncSessionLocal
from app.models.identity import HumanAccount, OpenReviewId
from app.core.security import hash_password


def _prompt_password() -> str:
    pw = os.environ.get("SUPERUSER_PASSWORD")
    if pw:
        return pw
    pw1 = getpass.getpass("Password: ")
    pw2 = getpass.getpass("Confirm:  ")
    if pw1 != pw2:
        print("Passwords do not match.", file=sys.stderr)
        sys.exit(2)
    if len(pw1) < 12:
        print("Password must be at least 12 characters.", file=sys.stderr)
        sys.exit(2)
    return pw1


def _prompt(var: str, label: str) -> str:
    v = os.environ.get(var)
    if v:
        return v
    v = input(f"{label}: ").strip()
    if not v:
        print(f"{label} is required.", file=sys.stderr)
        sys.exit(2)
    return v


async def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--email", required=True, help="Email of the account to promote")
    ap.add_argument("--create", action="store_true",
                    help="Create the account if it does not exist (prompts for name, password, openreview_id)")
    args = ap.parse_args()

    async with AsyncSessionLocal() as db:
        existing = (await db.execute(
            select(HumanAccount).where(HumanAccount.email == args.email)
        )).scalar_one_or_none()

        if existing:
            if existing.is_superuser:
                print(f"{args.email} is already a superuser — no change.")
                return 0
            existing.is_superuser = True
            await db.commit()
            print(f"Promoted {args.email} to superuser.")
            return 0

        if not args.create:
            print(
                f"No account found for {args.email}.\n"
                f"Rerun with --create to make a new superuser account, or have\n"
                f"the user sign up through the UI first.",
                file=sys.stderr,
            )
            return 1

        name = _prompt("SUPERUSER_NAME", "Full name")
        openreview_id = _prompt("SUPERUSER_OPENREVIEW_ID", "OpenReview ID (e.g. ~Your_Name1)")
        password = _prompt_password()

        # Guard against duplicate openreview_id collisions before hashing work.
        dup_or = (await db.execute(
            select(OpenReviewId).where(OpenReviewId.value == openreview_id)
        )).scalar_one_or_none()
        if dup_or:
            print(f"OpenReview ID '{openreview_id}' is already claimed.", file=sys.stderr)
            return 1

        user = HumanAccount(
            name=name,
            email=args.email,
            hashed_password=hash_password(password),
            is_superuser=True,
            openreview_ids=[OpenReviewId(value=openreview_id)],
        )
        db.add(user)
        await db.commit()
        print(f"Created superuser {args.email} (id={user.id}).")
        return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
