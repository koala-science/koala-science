"""Signing up without a working mail sender.

Internal testing needs people to onboard themselves before a real sender is
configured. With `SELF_SERVE_VERIFICATION` on, signup hands the verification
token back in its response instead of relying on mail nobody will receive, and
the frontend sends the person straight to the page that redeems it.

What this gives up is precise: proof that the person controls the address. What
it does NOT give up is the identity check — the OpenReview domain match still
runs, so nobody can claim a researcher's ID from an unrelated address. And it
must never hand back a token for an address that is already verified, which
would turn a public endpoint into account takeover.
"""
import uuid

import pytest
from httpx import AsyncClient

from app.core.config import settings
from tests.conftest import mark_email_verified

PASSWORD = "secure_password_123"


def _payload(domain: str = "example.com") -> dict:
    """`example.com` because conftest's autouse OpenReview stub lists it, and
    because a generated address at a live domain is one misconfigured key away
    from mailing a stranger."""
    return {
        "email": f"selfserve_{uuid.uuid4().hex[:10]}@{domain}",
        "openreview_id": f"~Self_Serve_{uuid.uuid4().hex[:8]}1",
    }


@pytest.fixture
def self_serve(monkeypatch):
    monkeypatch.setattr(settings, "SELF_SERVE_VERIFICATION", True)


def test_it_is_off_unless_someone_turns_it_on():
    """The default is what production runs until it is deliberately changed."""
    assert settings.SELF_SERVE_VERIFICATION is False


async def test_the_token_is_withheld_when_the_flag_is_off(client: AsyncClient):
    resp = await client.post("/api/v1/auth/signup", json=_payload())
    assert resp.status_code == 201, resp.text
    assert resp.json()["verification_token"] is None


async def test_a_returned_token_actually_finishes_the_account(
    client: AsyncClient, self_serve
):
    """End to end, the way a person would: no mailbox involved at any point."""
    payload = _payload()
    resp = await client.post("/api/v1/auth/signup", json=payload)
    assert resp.status_code == 201, resp.text

    token = resp.json()["verification_token"]
    assert token

    verified = await client.post(
        "/api/v1/auth/verify",
        json={"token": token, "name": "Self Serve", "password": PASSWORD},
    )
    assert verified.status_code == 200, verified.text

    login = await client.post(
        "/api/v1/auth/login", json={"email": payload["email"], "password": PASSWORD}
    )
    assert login.status_code == 200, login.text


async def test_an_already_verified_address_gets_no_token(
    client: AsyncClient, self_serve
):
    """The account-takeover guard: a public endpoint must not hand out a token
    that rewrites the credentials of an account somebody already holds."""
    payload = _payload()
    first = await client.post("/api/v1/auth/signup", json=payload)
    assert first.status_code == 201, first.text
    await mark_email_verified(payload["email"], PASSWORD)

    again = await client.post(
        "/api/v1/auth/signup",
        json={"email": payload["email"], "openreview_id": _payload()["openreview_id"]},
    )
    assert again.status_code == 201, again.text
    assert again.json()["verification_token"] is None


async def test_the_mail_cooldown_does_not_withhold_the_token(
    client: AsyncClient, self_serve
):
    """Two signups in a row self-serve both times.

    The cooldown exists to stop mail being re-sent; with nothing being mailed it
    must not be what decides whether a person can get in.
    """
    payload = _payload()
    first = await client.post("/api/v1/auth/signup", json=payload)
    assert first.status_code == 201, first.text
    assert first.json()["verification_token"]

    second = await client.post(
        "/api/v1/auth/signup",
        json={"email": payload["email"], "openreview_id": _payload()["openreview_id"]},
    )
    assert second.status_code == 201, second.text
    assert second.json()["verification_token"]


async def test_the_identity_check_still_runs(client: AsyncClient, self_serve):
    """Self-serve is not a way around the OpenReview domain match."""
    resp = await client.post(
        "/api/v1/auth/signup", json=_payload(domain="unrelated-university.edu")
    )
    assert resp.status_code == 422, resp.text
    assert "not at an institution" in resp.json()["detail"]


async def test_the_race_path_withholds_the_token_for_a_verified_winner(
    client: AsyncClient, self_serve, monkeypatch
):
    """The same account-takeover guard, on the path that reaches it by losing a race.

    Two signups for one address can both pass the "is there a row for this email"
    check and collide on the unique index. The loser re-reads the winning row —
    which may by then be verified, since nothing holds it unverified between the
    two statements. Handing a token back there would rewrite the credentials of
    an account somebody already holds.

    Forced rather than raced: the patched `flush` creates and verifies the
    colliding row itself, then raises the violation the real collision would.
    """
    from sqlalchemy.exc import IntegrityError
    from sqlalchemy.ext.asyncio import AsyncSession

    payload = _payload()

    # A verified account for this address, created and abandoned so the signup
    # below cannot see it in its own session until after the collision.
    setup = await client.post("/api/v1/auth/signup", json=_payload())
    assert setup.status_code == 201, setup.text

    real_flush = AsyncSession.flush
    collided = {"done": False}

    async def _collide_once(self, *args, **kwargs):
        if not collided["done"]:
            collided["done"] = True
            await _insert_verified_account(payload["email"])
            # The index name has to be on `orig`: that is what the handler
            # inspects to tell this collision from any other.
            raise IntegrityError(
                "INSERT INTO human_account ...",
                None,
                Exception(
                    "duplicate key value violates unique constraint "
                    '"ix_human_account_email"'
                ),
            )
        return await real_flush(self, *args, **kwargs)

    monkeypatch.setattr(AsyncSession, "flush", _collide_once)

    resp = await client.post("/api/v1/auth/signup", json=payload)
    assert resp.status_code == 201, resp.text
    assert collided["done"], "the collision never fired; this test proved nothing"
    assert resp.json()["verification_token"] is None


async def _insert_verified_account(email: str) -> None:
    """A verified human, inserted the way the race's winner would already exist.

    Through the ORM rather than raw SQL: the model already knows every NOT NULL
    column and the joined actor row, so this does not drift with the schema.
    """
    import uuid as _uuid

    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from app.core.config import settings as _settings
    from app.core.security import hash_password
    from app.models.identity import HumanAccount

    engine = create_async_engine(str(_settings.DATABASE_URL), pool_pre_ping=True)
    try:
        async with async_sessionmaker(engine)() as session:
            session.add(
                HumanAccount(
                    name=email.split("@")[0],
                    email=email,
                    hashed_password=hash_password(PASSWORD),
                    email_verified=True,
                    openreview_id=f"~Race_Winner_{_uuid.uuid4().hex[:8]}1",
                )
            )
            await session.commit()
    finally:
        await engine.dispose()
