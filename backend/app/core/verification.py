"""Email-verification tokens.

The raw token exists only in the email. What is stored is its SHA-256, so a leak
of the table does not hand anyone a working link.
"""
import hashlib
import secrets
from datetime import UTC, datetime, timedelta

TOKEN_TTL = timedelta(hours=24)


def new_token() -> tuple[str, str]:
    """A raw token for the link, and the hash to store beside it."""
    raw = secrets.token_urlsafe(32)
    return raw, hash_token(raw)


def hash_token(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


def expiry_from(now: datetime | None = None) -> datetime:
    return (now or datetime.now(UTC)) + TOKEN_TTL
