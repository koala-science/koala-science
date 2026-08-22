"""Signup gates: institutional address, matched to the claimed profile, then proven.

An account's email is the whole basis for believing its OpenReview ID, so the
address has to be institutional, has to sit at a domain that profile lists, and
has to be proven by a link before the account can do anything.
"""
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.core.config import settings
from app.core.openreview import OpenReviewProfile, OpenReviewUnavailableError
from app.core.verification import hash_token

PASSWORD = "secure_password_123"


def _unique_email(domain: str = "example.com") -> str:
    return f"verify_{uuid.uuid4().hex[:10]}@{domain}"


def _unique_openreview_id() -> str:
    return f"~Verify_User_{uuid.uuid4().hex[:8]}1"


def _payload(email: str) -> dict:
    """Signup asks only for the address and the claim; credentials come later."""
    return {"email": email, "openreview_id": _unique_openreview_id()}


def _redeem(token: str, *, name: str = "Verify User", password: str = PASSWORD) -> dict:
    return {"token": token, "name": name, "password": password}


def _profile_listing(*domains):
    async def _stub(openreview_id: str) -> OpenReviewProfile:
        return OpenReviewProfile(
            id=openreview_id, name="Verify User", email_domains=domains
        )
    return _stub


@pytest.fixture
def sent(monkeypatch):
    """Capture what would have been emailed."""
    outbox: list[dict] = []

    async def _capture(*, to, subject, html, text):
        outbox.append({"to": to, "subject": subject, "html": html, "text": text})

    import app.api.v1.endpoints.auth as auth_module

    monkeypatch.setattr(auth_module, "send_email", _capture)
    return outbox


def _link_token(message: dict) -> str:
    return message["text"].split("token=")[1].split()[0]


async def _age_mail_clock(email: str) -> None:
    """Push this account past the send cooldown."""
    engine = create_async_engine(str(settings.DATABASE_URL), pool_pre_ping=True)
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "UPDATE human_account SET last_verification_mail_at = "
                "last_verification_mail_at - interval '1 hour' WHERE email = :e"
            ),
            {"e": email},
        )
    await engine.dispose()


async def _token_row(email: str) -> dict | None:
    engine = create_async_engine(str(settings.DATABASE_URL), pool_pre_ping=True)
    try:
        async with engine.begin() as conn:
            row = (
                await conn.execute(
                    text(
                        "SELECT t.id, t.used_at, t.expires_at FROM email_verification_token t "
                        "JOIN human_account h ON h.id = t.human_account_id "
                        "WHERE h.email = :e ORDER BY t.created_at DESC LIMIT 1"
                    ),
                    {"e": email},
                )
            ).mappings().first()
            return dict(row) if row else None
    finally:
        await engine.dispose()


async def test_free_email_is_refused_before_openreview_is_consulted(
    client: AsyncClient, monkeypatch, sent
):
    """Cheapest gate first: a refused address must not cost an API round trip."""
    called = False

    async def _tripwire(openreview_id: str):
        nonlocal called
        called = True
        return None

    import app.api.v1.endpoints.auth as auth_module
    monkeypatch.setattr(auth_module, "fetch_profile", _tripwire)

    resp = await client.post("/api/v1/auth/signup", json=_payload(_unique_email("gmail.com")))

    assert resp.status_code == 422
    assert "institutional" in resp.json()["detail"].lower()
    assert called is False
    assert sent == []


async def test_domain_absent_from_the_profile_is_refused(
    client: AsyncClient, monkeypatch, sent
):
    import app.api.v1.endpoints.auth as auth_module
    monkeypatch.setattr(auth_module, "fetch_profile", _profile_listing("mila.quebec"))

    resp = await client.post("/api/v1/auth/signup", json=_payload(_unique_email("mcgill.ca")))

    assert resp.status_code == 422
    assert "not at an institution" in resp.json()["detail"]
    assert sent == []


async def test_profile_with_only_free_domains_is_refused_with_guidance(
    client: AsyncClient, monkeypatch, sent
):
    import app.api.v1.endpoints.auth as auth_module
    monkeypatch.setattr(auth_module, "fetch_profile", _profile_listing("gmail.com"))

    resp = await client.post("/api/v1/auth/signup", json=_payload(_unique_email("mila.quebec")))

    assert resp.status_code == 422
    detail = resp.json()["detail"]
    assert "no institutional email" in detail
    assert "OpenReview profile" in detail


async def test_subdomain_of_a_listed_domain_is_accepted(
    client: AsyncClient, monkeypatch, sent
):
    import app.api.v1.endpoints.auth as auth_module
    monkeypatch.setattr(auth_module, "fetch_profile", _profile_listing("stanford.edu"))

    resp = await client.post(
        "/api/v1/auth/signup", json=_payload(_unique_email("cs.stanford.edu"))
    )

    assert resp.status_code == 201, resp.text
    assert len(sent) == 1


async def test_openreview_outage_is_503_not_a_rejection(
    client: AsyncClient, monkeypatch, sent
):
    """An unanswerable lookup must never be reported as a bad OpenReview ID."""
    async def _down(openreview_id: str):
        raise OpenReviewUnavailableError("challenge")

    import app.api.v1.endpoints.auth as auth_module
    monkeypatch.setattr(auth_module, "fetch_profile", _down)

    resp = await client.post("/api/v1/auth/signup", json=_payload(_unique_email("mila.quebec")))

    assert resp.status_code == 503
    assert sent == []


async def test_signup_sends_a_link_and_withholds_tokens(client: AsyncClient, sent):
    email = _unique_email()
    resp = await client.post("/api/v1/auth/signup", json=_payload(email))

    assert resp.status_code == 201
    body = resp.json()
    assert body == {"verification_required": True, "email": email}
    assert len(sent) == 1 and sent[0]["to"] == email
    assert "token=" in sent[0]["text"]


async def test_login_is_blocked_until_the_link_is_clicked(client: AsyncClient, sent):
    email = _unique_email()
    await client.post("/api/v1/auth/signup", json=_payload(email))

    blocked = await client.post(
        "/api/v1/auth/login", json={"email": email, "password": PASSWORD}
    )
    assert blocked.status_code == 401, "an unverified account simply does not authenticate"

    verified = await client.post(
        "/api/v1/auth/verify", json=_redeem(_link_token(sent[0]))
    )
    assert verified.status_code == 200

    allowed = await client.post(
        "/api/v1/auth/login", json={"email": email, "password": PASSWORD}
    )
    assert allowed.status_code == 200
    assert "access_token" in allowed.json()


async def test_a_token_cannot_be_used_twice(client: AsyncClient, sent):
    email = _unique_email()
    await client.post("/api/v1/auth/signup", json=_payload(email))
    token = _link_token(sent[0])

    assert (await client.post("/api/v1/auth/verify", json=_redeem(token))).status_code == 200
    second = await client.post("/api/v1/auth/verify", json=_redeem(token))

    assert second.status_code == 400
    assert second.json()["detail"]["code"] == "INVALID_OR_EXPIRED_TOKEN"


async def test_an_unknown_token_is_refused(client: AsyncClient):
    resp = await client.post("/api/v1/auth/verify", json=_redeem("not-a-real-token"))
    assert resp.status_code == 400


async def test_an_expired_token_is_refused(client: AsyncClient, sent):
    email = _unique_email()
    await client.post("/api/v1/auth/signup", json=_payload(email))
    token = _link_token(sent[0])

    engine = create_async_engine(str(settings.DATABASE_URL), pool_pre_ping=True)
    async with engine.begin() as conn:
        await conn.execute(
            text("UPDATE email_verification_token SET expires_at = :t WHERE token_hash = :h"),
            {"t": datetime.now(UTC) - timedelta(minutes=1), "h": hash_token(token)},
        )
    await engine.dispose()

    resp = await client.post("/api/v1/auth/verify", json=_redeem(token))
    assert resp.status_code == 400


async def test_the_raw_token_is_never_stored(client: AsyncClient, sent):
    email = _unique_email()
    await client.post("/api/v1/auth/signup", json=_payload(email))
    token = _link_token(sent[0])

    engine = create_async_engine(str(settings.DATABASE_URL), pool_pre_ping=True)
    async with engine.begin() as conn:
        hit = (
            await conn.execute(
                text("SELECT count(*) FROM email_verification_token WHERE token_hash = :raw"),
                {"raw": token},
            )
        ).scalar()
    await engine.dispose()

    assert hit == 0, "the raw token must not appear in the table"


async def test_a_resend_does_not_invalidate_the_earlier_link(client: AsyncClient, sent):
    """Resend is unauthenticated, so retiring live links would hand anyone a way
    to break the one a real user is waiting on. Both work; the first redeemed
    wins and kills the rest."""
    email = _unique_email()
    await client.post("/api/v1/auth/signup", json=_payload(email))
    first = _link_token(sent[0])

    await _age_mail_clock(email)
    resp = await client.post(
        "/api/v1/auth/resend-verification", json={"email": email}
    )
    assert resp.status_code == 200
    assert len(sent) == 2

    assert (await client.post("/api/v1/auth/verify", json=_redeem(first))).status_code == 200

    spent = await client.post("/api/v1/auth/verify", json=_redeem(_link_token(sent[1])))
    assert spent.status_code == 400, "verifying the address kills every other link"


async def test_resend_does_not_reveal_whether_an_account_exists(
    client: AsyncClient, sent
):
    resp = await client.post(
        "/api/v1/auth/resend-verification",
        json={"email": _unique_email()},
    )

    assert resp.status_code == 200
    assert resp.json() == {"ok": True}
    assert sent == [], "nothing may be sent for an address with no account"


def test_the_migration_creates_every_column_the_model_declares():
    """Migration and model must agree about `email_verification_token`.

    The suite builds its schema with `Base.metadata.create_all`, so a column the
    model declares and the migration omits passes every test here and then 500s
    against a database built the real way. That is exactly how `updated_at` —
    inherited from `Base`, easy to forget — was missed.
    """
    import re
    from pathlib import Path

    from app.models.identity import EmailVerificationToken

    migration = (
        Path(__file__).resolve().parents[1]
        / "alembic" / "versions" / "059_email_verification.py"
    ).read_text()
    create = migration.split('op.create_table(\n        "email_verification_token"')[1]
    create = create.split("op.create_index")[0]
    in_migration = set(re.findall(r'sa\.Column\(\s*"([a-z_]+)"', create))

    declared = {c.name for c in EmailVerificationToken.__table__.columns}
    assert declared <= in_migration, f"missing from the migration: {declared - in_migration}"


def test_operator_created_accounts_can_log_in():
    """The scripts that bootstrap an environment must not lock it out.

    `email_verified` defaults to false and login refuses an unverified account.
    An operator creating the first superuser has no way to receive the link —
    nothing is configured to send it — so these accounts are born verified.

    Parsed with `ast` rather than a regex: a text search has to guess at
    formatting, and a pattern anchored on the closing paren silently finds
    nothing in a single-line call, which then passes vacuously.
    """
    import ast
    from pathlib import Path

    scripts = Path(__file__).resolve().parents[1] / "scripts"
    checked = 0
    for name in ("grant_superuser.py", "seed.py", "seed_benchmarks.py"):
        tree = ast.parse((scripts / name).read_text())
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            if getattr(node.func, "id", None) != "HumanAccount":
                continue
            checked += 1
            verified = [
                kw for kw in node.keywords
                if kw.arg == "email_verified"
                and isinstance(kw.value, ast.Constant)
                and kw.value.value is True
            ]
            assert verified, f"{name} creates a HumanAccount that can never log in"

    assert checked == 3, f"expected 3 creation sites, found {checked}"


@pytest.mark.parametrize("bad", ["stanford.edu", "@stanford.edu", "alice@", "a b@x.edu", "alice@localhost"])
async def test_an_unparseable_address_is_refused(client: AsyncClient, bad):
    """`rpartition("@")` on an @-less string returns the whole string as the
    domain, which would clear both the free-mail gate and the profile match."""
    resp = await client.post("/api/v1/auth/signup", json=_payload(bad))
    assert resp.status_code == 422, resp.text


async def test_the_address_is_stored_lowercase(client: AsyncClient, sent):
    """The unique index is case-sensitive; two casings must not be two accounts."""
    local = f"Mixed_{uuid.uuid4().hex[:8]}"
    await client.post("/api/v1/auth/signup", json=_payload(f"{local}@Example.com"))

    engine = create_async_engine(str(settings.DATABASE_URL), pool_pre_ping=True)
    async with engine.begin() as conn:
        stored = (
            await conn.execute(
                text("SELECT email FROM human_account WHERE lower(email) = :e"),
                {"e": f"{local.lower()}@example.com"},
            )
        ).scalar()
    await engine.dispose()

    assert stored == f"{local.lower()}@example.com"


async def test_signup_does_not_disclose_that_an_email_is_registered(
    client: AsyncClient, monkeypatch, sent
):
    """One signup request answers the same way, for every input that could vary.

    Comparing two identical payloads proves almost nothing: what leaks is a
    payload that fails a *later* check. If the address were looked at first, a
    registered address would short-circuit to 201 while an unregistered one
    reached the failing check and returned 409 or 422.

    The registered address here is *verified*, which is the branch that actually
    diverges — an unverified row behaves like a fresh one in most of these paths.

    This is a claim about a single request. It is not a claim that registration
    status is unobtainable; see the signup docstring.
    """
    registered = _unique_email()
    await client.post("/api/v1/auth/signup", json=_payload(registered))
    await client.post("/api/v1/auth/verify", json=_redeem(_link_token(sent[-1])))
    unregistered = _unique_email()

    taken = _payload(_unique_email())
    await client.post("/api/v1/auth/signup", json=taken)

    import app.api.v1.endpoints.auth as auth_module

    async def _no_profile(openreview_id: str):
        return None

    probes = {
        "an OpenReview ID already registered": lambda e: {
            **_payload(e), "openreview_id": taken["openreview_id"]
        },
        "an OpenReview ID that does not exist": lambda e: _payload(e),
        "a domain the profile does not list": lambda e: _payload(e),
    }

    for label, build in probes.items():
        if label == "an OpenReview ID that does not exist":
            monkeypatch.setattr(auth_module, "fetch_profile", _no_profile)
        elif label == "a domain the profile does not list":
            monkeypatch.setattr(
                auth_module, "fetch_profile", _profile_listing("mila.quebec")
            )

        known = await client.post("/api/v1/auth/signup", json=build(registered))
        unknown = await client.post("/api/v1/auth/signup", json=build(unregistered))

        assert known.status_code == unknown.status_code, (
            f"{label}: registered {known.status_code} vs "
            f"unregistered {unknown.status_code} — signup reports membership"
        )


async def test_a_second_signup_cannot_invalidate_the_first_link(
    client: AsyncClient, sent
):
    """Anyone can post a signup for any address. If that retired live links, it
    would be a way to stop someone else's signup completing."""
    email = _unique_email()
    await client.post("/api/v1/auth/signup", json=_payload(email))
    first_token = _link_token(sent[0])

    await _age_mail_clock(email)
    await client.post("/api/v1/auth/signup", json=_payload(email))

    assert len(sent) == 2
    assert (
        await client.post("/api/v1/auth/verify", json=_redeem(first_token))
    ).status_code == 200


async def test_signing_up_over_a_verified_account_tells_the_mailbox_not_the_caller(
    client: AsyncClient, sent
):
    email = _unique_email()
    await client.post("/api/v1/auth/signup", json=_payload(email))
    await client.post("/api/v1/auth/verify", json=_redeem(_link_token(sent[0])))
    sent.clear()

    resp = await client.post("/api/v1/auth/signup", json=_payload(email))

    assert resp.status_code == 201
    assert len(sent) == 1
    assert sent[0]["to"] == email
    assert "already have" in sent[0]["subject"].lower()
    assert "token=" not in sent[0]["text"], "no fresh link for a verified account"


async def test_a_verified_openreview_id_is_reported_at_signup(client: AsyncClient, sent):
    """Once an ID is actually held, saying so is right: the caller does not hold
    that account, so there is no inbox to explain it through."""
    payload = _payload(_unique_email())
    await client.post("/api/v1/auth/signup", json=payload)
    await client.post("/api/v1/auth/verify", json=_redeem(_link_token(sent[0])))

    clash = _payload(_unique_email())
    clash["openreview_id"] = payload["openreview_id"]
    resp = await client.post("/api/v1/auth/signup", json=clash)

    assert resp.status_code == 409
    assert "OpenReview ID" in resp.json()["detail"]


async def test_an_unredeemed_signup_does_not_hold_the_openreview_id(
    client: AsyncClient, sent
):
    """A pending signup must not park someone else's identity.

    It also closes an oracle: if an unredeemed signup claimed the ID, a second
    request could ask "was that address already registered?" by watching whether
    the ID came back taken.
    """
    first = _payload(_unique_email())
    await client.post("/api/v1/auth/signup", json=first)

    second = _payload(_unique_email())
    second["openreview_id"] = first["openreview_id"]
    resp = await client.post("/api/v1/auth/signup", json=second)
    assert resp.status_code == 201, "an unredeemed claim holds nothing"

    # Whoever redeems first gets it; the other is told at redemption.
    assert (
        await client.post("/api/v1/auth/verify", json=_redeem(_link_token(sent[0])))
    ).status_code == 200
    loser = await client.post("/api/v1/auth/verify", json=_redeem(_link_token(sent[1])))
    assert loser.status_code == 409
    assert loser.json()["detail"]["code"] == "OPENREVIEW_ID_TAKEN"


async def test_a_second_link_is_not_mailed_inside_the_cooldown(client: AsyncClient, sent):
    """Signup answers the same for a registered address, so an unauthenticated
    caller picks who gets this mail. Without the cooldown that is a way to flood
    someone's inbox at the IP rate limit."""
    email = _unique_email()
    await client.post("/api/v1/auth/signup", json=_payload(email))
    assert len(sent) == 1

    for _ in range(3):
        await client.post(
            "/api/v1/auth/resend-verification",
            json={"email": email},
        )
        await client.post("/api/v1/auth/signup", json=_payload(email))

    assert len(sent) == 1, "the cooldown must suppress repeat sends"


async def test_the_existing_account_notice_is_also_throttled(client: AsyncClient, sent):
    email = _unique_email()
    await client.post("/api/v1/auth/signup", json=_payload(email))
    await client.post("/api/v1/auth/verify", json=_redeem(_link_token(sent[0])))
    sent.clear()

    for _ in range(3):
        await client.post("/api/v1/auth/signup", json=_payload(email))

    assert len(sent) == 1, "one notice, however many times signup is replayed"


async def test_a_signup_posted_by_a_stranger_cannot_become_their_account(
    client: AsyncClient, sent
):
    """The takeover this design exists to prevent.

    Anyone can post a signup for any address, and the mail that results is
    indistinguishable from a wanted one — a stranger can put the victim's own
    public OpenReview ID on it. What stops the attack is that the link installs
    no credentials: whoever reads the mailbox sets the name and password, so the
    account that results is theirs.
    """
    email = _unique_email()

    # A stranger posts the signup, claiming an identity of their choosing.
    await client.post("/api/v1/auth/signup", json=_payload(email))

    # The mailbox holder clicks and sets their own credentials.
    await client.post(
        "/api/v1/auth/verify",
        json=_redeem(_link_token(sent[0]), name="Real Owner", password="owner_password_123"),
    )

    as_owner = await client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": "owner_password_123"},
    )
    assert as_owner.status_code == 200
    assert as_owner.json()["name"] == "Real Owner"


async def test_the_requester_learns_no_secret_that_would_let_them_in(
    client: AsyncClient, sent
):
    """A stranger who posts the signup knows everything they submitted — and none
    of it is a credential, because signup takes none."""
    email = _unique_email()
    payload = _payload(email)
    await client.post("/api/v1/auth/signup", json=payload)

    assert "password" not in payload
    assert set(payload) == {"email", "openreview_id"}

    await client.post(
        "/api/v1/auth/verify",
        json=_redeem(_link_token(sent[0]), password="chosen_by_the_holder_1"),
    )

    for guess in ("chosen_by_the_holder_1", "password123", payload["openreview_id"]):
        attempt = await client.post(
            "/api/v1/auth/login", json={"email": email, "password": guess}
        )
        if guess == "chosen_by_the_holder_1":
            assert attempt.status_code == 200
        else:
            assert attempt.status_code == 401


async def test_the_mail_names_the_identity_being_claimed(client: AsyncClient, sent):
    """The holder has to be able to see whose identity a link would attach."""
    email = _unique_email()
    payload = _payload(email)
    await client.post("/api/v1/auth/signup", json=payload)

    body = sent[0]["text"]
    assert payload["openreview_id"] in body


async def test_the_mail_cannot_carry_injected_markup(client: AsyncClient, sent, monkeypatch):
    """Every interpolated value is escaped.

    The message is sent from a domain whose reputation is the platform's, to an
    address the sender chooses, so unescaped input here is arbitrary HTML mailed
    by us on a stranger's behalf.
    """
    import app.api.v1.endpoints.auth as auth_module

    async def _hostile_profile(openreview_id: str):
        from app.core.openreview import OpenReviewProfile

        return OpenReviewProfile(
            id=openreview_id,
            name='</strong></p><p><a href="https://evil.tld">Claim your paper</a><!--',
            email_domains=("example.com",),
        )

    monkeypatch.setattr(auth_module, "fetch_profile", _hostile_profile)
    await client.post("/api/v1/auth/signup", json=_payload(_unique_email()))

    assert "<a href=\"https://evil.tld\"" not in sent[0]["html"]
    assert "&lt;a href=" in sent[0]["html"]


async def test_login_treats_a_pending_signup_exactly_like_a_bad_password(
    client: AsyncClient, sent
):
    """Answering "verify your email" here would be an enumeration oracle: anyone
    can post a signup for any address, and the reply would then report whether
    that address already had a verified account."""
    email = _unique_email()
    await client.post("/api/v1/auth/signup", json=_payload(email))

    first = await client.post(
        "/api/v1/auth/login", json={"email": email, "password": PASSWORD}
    )
    second = await client.post(
        "/api/v1/auth/login", json={"email": email, "password": "not_the_password_1"}
    )

    assert first.status_code == 401
    assert first.json() == second.json()


async def test_verification_requires_a_password_of_its_own(client: AsyncClient, sent):
    email = _unique_email()
    await client.post("/api/v1/auth/signup", json=_payload(email))

    short = await client.post(
        "/api/v1/auth/verify",
        json={"token": _link_token(sent[0]), "name": "X", "password": "short"},
    )
    assert short.status_code == 422

    missing = await client.post(
        "/api/v1/auth/verify", json={"token": _link_token(sent[0])}
    )
    assert missing.status_code == 422


async def test_a_later_signup_is_the_claim_the_next_link_carries(
    client: AsyncClient, sent
):
    """Recording a claim must not be throttled along with mailing one.

    Gating both on the cooldown dropped whichever signup arrived second: the
    caller got "check your email" for mail nobody would send, and the next
    resend re-mailed the earlier claim. With an attacker posting first that
    means the victim's own address ends up verified against someone else's
    OpenReview identity, permanently — nothing in the API can change it later.
    """
    email = _unique_email()

    first = _payload(email)
    await client.post("/api/v1/auth/signup", json=first)

    # Inside the cooldown: no mail goes out, but the claim must still be kept.
    second = _payload(email)
    await client.post("/api/v1/auth/signup", json=second)
    assert len(sent) == 1, "the cooldown still suppresses the second mail"

    await _age_mail_clock(email)
    await client.post("/api/v1/auth/resend-verification", json={"email": email})

    assert len(sent) == 2
    assert second["openreview_id"] in sent[1]["text"]
    assert first["openreview_id"] not in sent[1]["text"]

    await client.post("/api/v1/auth/verify", json=_redeem(_link_token(sent[1])))

    engine = create_async_engine(str(settings.DATABASE_URL), pool_pre_ping=True)
    async with engine.begin() as conn:
        claimed = (
            await conn.execute(
                text("SELECT openreview_id FROM human_account WHERE email = :e"),
                {"e": email},
            )
        ).scalar()
    await engine.dispose()

    assert claimed == second["openreview_id"]


async def test_a_corrected_openreview_id_is_not_swallowed(client: AsyncClient, sent):
    """The same bug with nobody malicious: mistype the ID, notice, re-submit."""
    email = _unique_email()
    await client.post("/api/v1/auth/signup", json=_payload(email))

    corrected = _payload(email)
    await client.post("/api/v1/auth/signup", json=corrected)

    await _age_mail_clock(email)
    await client.post("/api/v1/auth/resend-verification", json={"email": email})

    assert corrected["openreview_id"] in sent[-1]["text"]


async def test_signup_refuses_fields_it_does_not_use(client: AsyncClient):
    """A stale frontend sending a password would otherwise report success while
    the password was silently discarded."""
    payload = _payload(_unique_email())
    payload["password"] = "would_be_ignored_123"

    resp = await client.post("/api/v1/auth/signup", json=payload)

    assert resp.status_code == 422


async def test_the_newest_claim_is_the_one_recorded_last_not_the_one_started_first(
    client: AsyncClient, sent, monkeypatch
):
    """Which claim is newest must follow insert order, not transaction order.

    Postgres `now()` is the transaction's start time. This signup opens its
    transaction first and inserts its token last, so under `now()` it would be
    stamped older than a signup that began after it — and "the newest claim" is
    what decides which OpenReview identity the next link carries.
    """
    email = _unique_email()
    first = _payload(email)
    second = _payload(email)

    import app.api.v1.endpoints.auth as auth_module

    real_lookup = auth_module.fetch_profile
    seen: list[str] = []

    async def _interleaved(openreview_id: str):
        # Runs while the outer request's transaction is already open.
        seen.append(openreview_id)
        if len(seen) == 1:
            await client.post("/api/v1/auth/signup", json=second)
        return await real_lookup(openreview_id)

    monkeypatch.setattr(auth_module, "fetch_profile", _interleaved)
    resp = await client.post("/api/v1/auth/signup", json=first)
    assert resp.status_code == 201, resp.text

    await _age_mail_clock(email)
    await client.post("/api/v1/auth/resend-verification", json={"email": email})

    assert first["openreview_id"] in sent[-1]["text"], (
        "the claim recorded last must be the one the next link carries"
    )


async def test_a_signup_that_loses_the_insert_race_still_records_its_claim(
    client: AsyncClient, sent, monkeypatch
):
    """The `ix_human_account_email` race, reached deliberately.

    Two signups for one address can both pass the existence check and reach the
    insert. The loser must record what it claimed rather than answering "check
    your email" and dropping it — that is the same failure the mail cooldown
    used to have, with a shorter window.
    """
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.models.identity import HumanAccount

    email = _unique_email()
    first = _payload(email)
    second = _payload(email)

    real_flush = AsyncSession.flush
    raced = False

    async def _flush_after_racing(self, *args, **kwargs):
        # Race only the flush that carries the account insert. Autoflush fires
        # on every query, so hooking the first one would land before the email
        # lookup and the outer request would simply see the winner's row.
        nonlocal raced
        pending_account = any(isinstance(obj, HumanAccount) for obj in self.new)
        if pending_account and not raced:
            raced = True
            await client.post("/api/v1/auth/signup", json=second)
        return await real_flush(self, *args, **kwargs)

    # No monkeypatch.undo() here: it would revert every patch in scope,
    # including the outbox capture this test reads from. The `raced` flag is
    # what stops the hook interfering again.
    monkeypatch.setattr(AsyncSession, "flush", _flush_after_racing)
    resp = await client.post("/api/v1/auth/signup", json=first)

    assert resp.status_code == 201, resp.text
    assert raced, "the competing signup never ran"

    await _age_mail_clock(email)
    await client.post("/api/v1/auth/resend-verification", json={"email": email})

    assert first["openreview_id"] in sent[-1]["text"], (
        "the loser of the insert race dropped its claim"
    )
