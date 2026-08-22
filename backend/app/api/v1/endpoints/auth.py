"""
Authentication endpoints:
- Email/password signup and login (for humans)
- Agent API key registration and management
- Agent API key → JWT exchange (for computer-use agents in browsers)
- ORCID OAuth verification (for academic identity, not login)
"""
import logging
import html
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from jose import jwt
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, status, Response
from fastapi.responses import RedirectResponse
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
import httpx

from app.db.session import get_db
from app.core.config import settings
from app.core.rate_limit import limiter, AUTH_RATE_LIMIT
from app.core.security import (
    create_access_token,
    create_refresh_token,
    generate_api_key,
    hash_api_key,
    compute_key_lookup,
    decode_token,
    hash_password,
    verify_password,
)
from app.core.deps import get_current_actor
from app.core.email import EmailSendError, send_email
from app.core.email_domains import domain_of, domains_match, is_free_email
from app.core.openreview import OpenReviewUnavailableError, fetch_profile
from app.core.verification import expiry_from, hash_token, new_token
from app.models.identity import Actor, ActorType, EmailVerificationToken, HumanAccount, Agent
from app.schemas.auth import (
    SignupRequest,
    SignupResponse,
    VerifyEmailRequest,
    ResendVerificationRequest,
    LoginRequest,
    AgentKeyLoginRequest,
    AgentCreateRequest,
    AgentCreateResponse,
    AgentListResponse,
    TokenResponse,
)
from app.schemas.platform import OrcidConnectResponse, OrcidCallbackResponse, ScholarLinkResponse

logger = logging.getLogger(__name__)

router = APIRouter()


# --- Email/Password Auth ---


@router.post(
    "/signup", response_model=SignupResponse, status_code=status.HTTP_201_CREATED
)
@limiter.limit(AUTH_RATE_LIMIT)
async def signup(
    request: Request,
    payload: SignupRequest,
    background: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    """Begin a signup. No account can act until its address has been proven.

    Ordering is deliberate: every rejection below depends only on data the caller
    supplied — the OpenReview ID they claimed, the domain they typed — and the one
    check that consults the address runs last and answers the same way either way.

    What that buys is narrower than it looks, and worth stating plainly. It means
    a single signup request does not report whether an address is registered. It
    does not mean the fact is unobtainable: an OpenReview ID is claimed at
    redemption, so a second signup reusing the same ID reveals whether the first
    one created an account. Closing that would mean claiming identities on behalf
    of signups nobody has proven, which is worse.
    """
    if not settings.SIGNUPS_ENABLED:
        raise HTTPException(status_code=403, detail="Signup is disabled")

    signup_domain = domain_of(payload.email)
    if is_free_email(signup_domain):
        raise HTTPException(
            status_code=422,
            detail=(
                "Use your institutional email address. Free email providers "
                "cannot be matched to an OpenReview profile."
            ),
        )

    existing_openreview = await db.execute(
        select(HumanAccount).where(
            HumanAccount.openreview_id == payload.openreview_id
        )
    )
    if existing_openreview.scalar_one_or_none():
        # Explicit, unlike the email case below. An OpenReview ID is a public
        # identity, so confirming one is registered discloses little — and the
        # person hitting this does not hold that account, so there is no inbox to
        # explain it through. "Check your email" would leave them waiting for
        # mail that is never coming.
        raise HTTPException(
            status_code=409,
            detail="An account with this OpenReview ID already exists",
        )

    try:
        profile = await fetch_profile(payload.openreview_id)
    except OpenReviewUnavailableError:
        raise HTTPException(
            status_code=503,
            detail="OpenReview is unavailable, please try again later",
        )
    if profile is None:
        raise HTTPException(
            status_code=422, detail="OpenReview profile does not exist"
        )

    institutional = [d for d in profile.email_domains if not is_free_email(d)]
    if not institutional:
        raise HTTPException(
            status_code=422,
            detail=(
                "This OpenReview profile lists no institutional email address. "
                "Add your institutional address to your OpenReview profile, then "
                "sign up with it."
            ),
        )

    if not domains_match(signup_domain, profile.email_domains):
        raise HTTPException(
            status_code=422,
            detail=(
                "This email is not at an institution listed on that OpenReview "
                "profile. Sign up with an address at one of its institutions, or "
                "add this one to your OpenReview profile first."
            ),
        )

    existing = (
        await db.execute(
            select(HumanAccount).where(HumanAccount.email == payload.email)
        )
    ).scalar_one_or_none()

    # The canonical ID, not the string that was typed. OpenReview resolves
    # aliases — a renamed profile keeps its old usernames — so storing the
    # submitted string would let two spellings of one person hold two accounts,
    # each passing the uniqueness check.
    claim = _Claim(openreview_id=profile.id, openreview_name=profile.name)

    if existing is not None:
        if existing.email_verified:
            await _notify_existing_account(db, existing, background)
        else:
            # The row is left exactly as it is; what this signup claimed is
            # recorded as a new token. Whether a link goes out is decided inside,
            # by the cooldown.
            await _issue_verification_email(db, existing, claim, background)
        return SignupResponse(verification_required=True, email=payload.email)

    user = HumanAccount(
        # A placeholder until the address is proven; whoever redeems the link
        # supplies the real name along with their password.
        name=payload.email.split("@")[0],
        email=payload.email,
        # No credentials and no claimed identity until a link is redeemed. An
        # unverified row is a placeholder for an address, nothing more — which is
        # also why an unredeemed signup cannot hold an OpenReview ID away from
        # its owner, or report through a 409 that this address is registered.
        hashed_password=None,
        openreview_id=None,
    )
    db.add(user)
    # The checks above are statements away from this insert, so a concurrent
    # signup for the same email or OpenReview ID passes them and collides here.
    try:
        await db.flush()
        await db.refresh(user)
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        if "ix_human_account_email" not in str(exc.orig):
            raise
        # Lost a race with another signup for this address. Record the claim
        # against the row that won, rather than answering as though it had been
        # kept — dropping it here is the same failure the cooldown used to have,
        # with a shorter window.
        winner = (
            await db.execute(
                select(HumanAccount).where(HumanAccount.email == payload.email)
            )
        ).scalar_one()
        if not winner.email_verified:
            await _issue_verification_email(db, winner, claim, background)
        return SignupResponse(verification_required=True, email=payload.email)

    await _issue_verification_email(db, user, claim, background)

    return SignupResponse(verification_required=True, email=user.email)


@dataclass(frozen=True)
class _Claim:
    """The OpenReview identity a verification link stands for."""

    openreview_id: str
    openreview_name: str | None


# Signup answers identically for a registered and an unregistered address, which
# means an unauthenticated caller chooses who receives this mail. The cooldown is
# what keeps that from being a way to flood someone's inbox — the IP rate limit
# alone still allows thousands a day, and the sending domain's reputation is on
# the line as much as the recipient's patience.
SIGNUP_MAIL_COOLDOWN = timedelta(minutes=5)


def _recently(stamp: datetime | None) -> bool:
    return stamp is not None and datetime.now(UTC) - stamp < SIGNUP_MAIL_COOLDOWN


async def _notify_existing_account(
    db: AsyncSession, user: HumanAccount, background: BackgroundTasks
) -> None:
    if _recently(user.last_signup_notice_at):
        return
    user.last_signup_notice_at = datetime.now(UTC)
    await db.commit()
    background.add_task(_notify_account_exists, user.email)


async def _notify_account_exists(email: str) -> None:
    """Tell the mailbox holder, since signup told the caller nothing."""
    try:
        await send_email(
            to=email,
            subject="You already have a Koala Science account",
            html=(
                "<p>Someone tried to sign up with this address, which already has "
                "a verified account. If that was you, just log in.</p>"
            ),
            text=(
                "Someone tried to sign up with this address, which already has a "
                "verified account. If that was you, just log in."
            ),
        )
    except EmailSendError:
        logger.exception("existing-account notice failed for %s", email)


async def _issue_verification_email(
    db: AsyncSession,
    user: HumanAccount,
    claim: _Claim,
    background: BackgroundTasks,
) -> None:
    """Record what this signup claimed, and mail a link for it if allowed.

    Recording is unconditional and throttling applies only to the send. Gating
    both on one check meant a signup posted inside the cooldown was discarded
    outright — so a second person's claim, or your own correction of a mistyped
    ID, vanished behind a "check your email" that promised mail nobody would
    send, and the next resend re-mailed the stale claim instead.

    Outstanding links are deliberately left alone. Retiring them would let anyone
    who can post a signup invalidate the link someone else is waiting on. They
    are harmless: each is single-use, each names the claim it stands for, and all
    of them die the moment the address is verified.

    A send failure is logged rather than raised: the row exists and the user can
    ask for another link. Losing the signup because an email provider was briefly
    down would be the worse outcome.
    """
    raw, token_hash = new_token()
    db.add(
        EmailVerificationToken(
            human_account_id=user.id,
            token_hash=token_hash,
            expires_at=expiry_from(),
            pending_openreview_id=claim.openreview_id,
            pending_openreview_name=claim.openreview_name,
        )
    )

    may_send = not _recently(user.last_verification_mail_at)
    if may_send:
        user.last_verification_mail_at = datetime.now(UTC)
    await db.commit()

    if may_send:
        link = f"{settings.FRONTEND_URL}/auth/verify?token={raw}"
        background.add_task(_deliver, user.email, link, claim)


async def _deliver(email: str, link: str, claim: _Claim) -> None:
    # Every interpolated value is escaped. `openreview_id` is regex-constrained
    # and `openreview_name` comes from OpenReview, but both reach this template
    # from outside, and the message is sent from a domain whose reputation is the
    # platform's — unescaped input here is arbitrary HTML mailed from us to an
    # address the sender chooses.
    who = html.escape(claim.openreview_name or claim.openreview_id)
    identity = html.escape(claim.openreview_id)
    safe_link = html.escape(link, quote=True)
    try:
        await send_email(
            to=email,
            subject="Verify your email for Koala Science",
            html=(
                f"<p>Someone asked to create a Koala Science account for "
                f"<strong>{who}</strong> ({identity}) using this address.</p>"
                f'<p><a href="{safe_link}">Confirm and choose a password</a></p>'
                f"<p>You set the name and password on that page, so nobody who "
                f"cannot read this mailbox can use this link. It expires in 24 "
                f"hours; if you did not expect it, ignore it.</p>"
            ),
            text=(
                f"Someone asked to create a Koala Science account for {who} "
                f"({identity}) using this address.\n\n{link}\n\n"
                "You set the name and password on that page, so nobody who "
                "cannot read this mailbox can use this link. It expires in 24 "
                "hours; if you did not expect it, ignore it."
            ),
        )
    except EmailSendError:
        logger.exception("verification email failed for %s", email)


@router.post("/verify")
@limiter.limit(AUTH_RATE_LIMIT)
async def verify_email(
    request: Request,
    payload: VerifyEmailRequest,
    db: AsyncSession = Depends(get_db),
):
    """Redeem a verification link and finish the account.

    The account is created empty at signup and holds no credentials until here.
    Whoever can read the mailbox chooses the name and password, so a signup
    posted by someone else cannot become an account they control.
    """
    result = await db.execute(
        select(EmailVerificationToken).where(
            EmailVerificationToken.token_hash == hash_token(payload.token)
        )
    )
    token = result.scalar_one_or_none()

    if token is None or token.used_at is not None or token.expires_at < datetime.now(UTC):
        raise HTTPException(
            status_code=400,
            detail={"detail": "Invalid or expired token", "code": "INVALID_OR_EXPIRED_TOKEN"},
        )

    user = (
        await db.execute(
            select(HumanAccount).where(HumanAccount.id == token.human_account_id)
        )
    ).scalar_one()

    # Once an address is verified, every other link for it is dead. Whoever holds
    # the mailbox has chosen a submission; a second one must not overwrite it.
    if user.email_verified:
        raise HTTPException(
            status_code=400,
            detail={"detail": "Invalid or expired token", "code": "INVALID_OR_EXPIRED_TOKEN"},
        )

    # The OpenReview ID is claimed here rather than at signup: an unredeemed
    # signup must not hold an identity away from the person it belongs to.
    taken = (
        await db.execute(
            select(HumanAccount).where(
                HumanAccount.openreview_id == token.pending_openreview_id,
                HumanAccount.id != user.id,
            )
        )
    ).scalar_one_or_none()
    if taken is not None:
        token.used_at = datetime.now(UTC)
        await db.commit()
        raise HTTPException(
            status_code=409,
            detail={
                "detail": "An account with this OpenReview ID already exists",
                "code": "OPENREVIEW_ID_TAKEN",
            },
        )

    # Name and password come from whoever holds the mailbox, right now. That is
    # the point: a link cannot install credentials chosen by whoever requested
    # it, so posting a signup for someone else's address achieves nothing beyond
    # sending them a mail they can ignore.
    user.name = payload.name
    user.hashed_password = hash_password(payload.password)
    user.openreview_id = token.pending_openreview_id
    user.openreview_name = token.pending_openreview_name
    user.email_verified = True
    token.used_at = datetime.now(UTC)

    try:
        await db.commit()
    except IntegrityError as exc:
        # Lost a race with another redemption for the same OpenReview ID. Spend
        # the token rather than leaving it live: it can never succeed now.
        await db.rollback()
        await db.execute(
            update(EmailVerificationToken)
            .where(EmailVerificationToken.id == token.id)
            .values(used_at=datetime.now(UTC))
        )
        await db.commit()
        raise HTTPException(
            status_code=409,
            detail={
                "detail": "An account with this OpenReview ID already exists",
                "code": "OPENREVIEW_ID_TAKEN",
            },
        ) from exc

    return {"ok": True}


@router.post("/resend-verification")
@limiter.limit(AUTH_RATE_LIMIT)
async def resend_verification(
    request: Request,
    payload: ResendVerificationRequest,
    background: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    """Send another link for the pending signup on this address.

    No password is asked for, because a link installs nothing: whoever redeems it
    supplies their own name and password. What bounds this endpoint is the
    cooldown — without it, anyone could aim mail at any address.

    The status and body are identical either way, and the send is queued rather
    than awaited, so the response does not report whether an address is
    registered. Timing is not part of that claim; see the signup docstring.
    """
    result = await db.execute(
        select(HumanAccount).where(HumanAccount.email == payload.email)
    )
    user = result.scalar_one_or_none()

    if user is not None and not user.email_verified:
        newest = (
            await db.execute(
                select(EmailVerificationToken)
                .where(EmailVerificationToken.human_account_id == user.id)
                .order_by(
                    EmailVerificationToken.created_at.desc(),
                    EmailVerificationToken.id.desc(),
                )
                .limit(1)
            )
        ).scalar_one_or_none()
        if newest is not None:
            await _issue_verification_email(
                db,
                user,
                _Claim(
                    openreview_id=newest.pending_openreview_id,
                    openreview_name=newest.pending_openreview_name,
                ),
                background,
            )

    return {"ok": True}


@router.post("/login", response_model=TokenResponse)
@limiter.limit(AUTH_RATE_LIMIT)
async def login(
    request: Request,
    payload: LoginRequest,
    response: Response,
    db: AsyncSession = Depends(get_db),
):
    """Login with email and password."""
    result = await db.execute(
        select(HumanAccount).where(HumanAccount.email == payload.email)
    )
    user = result.scalar_one_or_none()

    # An unverified account holds no credentials — they sit on the pending signup
    # until its link is redeemed — so it simply fails to authenticate, exactly
    # like a wrong password. Answering "verify your email" here would be an
    # enumeration oracle: anyone could sign up for an address with a password of
    # their choosing and read registration status off the reply. The login page
    # offers the resend affordance unconditionally instead.
    if not user or not user.hashed_password or not verify_password(payload.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="Invalid email or password")

    if not user.is_active:
        raise HTTPException(status_code=403, detail="Account is deactivated")

    access_token = create_access_token(user.id, user.actor_type.value)
    refresh_token = create_refresh_token(user.id)

    response.set_cookie(
        key="refresh_token",
        value=refresh_token,
        httponly=True,
        secure=False,
        samesite="lax",
        max_age=settings.REFRESH_TOKEN_EXPIRE_DAYS * 86400,
    )

    return TokenResponse(
        access_token=access_token,
        token_type="bearer",
        actor_id=user.id,
        actor_type=user.actor_type.value,
        name=user.name,
        is_superuser=user.is_superuser,
        is_annotator=user.is_annotator,
    )


# --- Agent API Key Login (for computer-use agents in the browser) ---


@router.post("/agents/login", response_model=TokenResponse)
@limiter.limit(AUTH_RATE_LIMIT)
async def agent_key_login(
    request: Request,
    payload: AgentKeyLoginRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    Login as an agent using an API key.
    Returns a JWT that can be used in the browser session.
    Designed for computer-use agents navigating the web UI.
    """
    from app.core.deps import _resolve_api_key_actor

    agent = await _resolve_api_key_actor(payload.api_key, db)

    access_token = create_access_token(agent.id, agent.actor_type.value)

    return TokenResponse(
        access_token=access_token,
        token_type="bearer",
        actor_id=agent.id,
        actor_type=agent.actor_type.value,
        name=agent.name,
    )


@router.post("/refresh", response_model=TokenResponse)
@limiter.limit(AUTH_RATE_LIMIT)
async def refresh_access_token(
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
    refresh_token: str | None = None,
):
    """Exchange a refresh token for a new access token."""
    if not refresh_token:
        raise HTTPException(status_code=401, detail="No refresh token provided")

    payload = decode_token(refresh_token)
    if not payload or not payload.get("refresh"):
        raise HTTPException(status_code=401, detail="Invalid refresh token")

    result = await db.execute(
        select(Actor).where(Actor.id == payload["sub"])
    )
    actor = result.scalar_one_or_none()
    if not actor or not actor.is_active:
        raise HTTPException(status_code=401, detail="Actor not found or inactive")

    # Unreachable today — a refresh cookie is only set at login, which already
    # refuses an unverified account — but the gate belongs here too rather than
    # resting on that being true of every other endpoint, now and later.
    if isinstance(actor, HumanAccount) and not actor.email_verified:
        raise HTTPException(
            status_code=403,
            detail={"detail": "Email not verified", "code": "EMAIL_NOT_VERIFIED"},
        )

    access_token = create_access_token(actor.id, actor.actor_type.value)

    return TokenResponse(
        access_token=access_token,
        token_type="bearer",
        actor_id=actor.id,
        actor_type=actor.actor_type.value,
        name=actor.name,
        is_superuser=isinstance(actor, HumanAccount) and actor.is_superuser,
        is_annotator=isinstance(actor, HumanAccount) and actor.is_annotator,
    )


async def _sync_actor_to_qdrant(actor):
    """Generate embedding and upsert actor to Qdrant. Best-effort."""
    try:
        from app.core.embeddings import generate_embedding
        from app.core.qdrant import upsert_actor

        desc = getattr(actor, "description", "") or ""
        text = f"{actor.name}\n\n{desc}" if desc else actor.name
        embedding = await generate_embedding(text)
        if embedding:
            created_at = int(actor.created_at.timestamp()) if actor.created_at else 0
            upsert_actor(
                actor.id, embedding,
                name=actor.name,
                actor_type=actor.actor_type.value,
                description=desc,
                created_at=created_at,
            )
    except Exception:
        pass  # Non-critical — backfill will catch it


# --- Agent Management (authenticated — humans only) ---

MAX_AGENTS_PER_USER = 3


@router.post(
    "/agents",
    response_model=AgentCreateResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_agent(
    request: AgentCreateRequest,
    actor: Actor = Depends(get_current_actor),
    db: AsyncSession = Depends(get_db),
):
    """
    Create a new agent owned by the authenticated human.
    Returns the API key — shown only once, never persisted in plaintext.
    Agents cannot create other agents (only humans can).
    A human may own at most 3 agents.
    """
    if not settings.SIGNUPS_ENABLED:
        raise HTTPException(status_code=403, detail="Signup is disabled")

    if actor.actor_type != ActorType.HUMAN:
        raise HTTPException(
            status_code=403, detail="Only human accounts can create agents"
        )

    owned = await db.scalar(
        select(func.count()).select_from(Agent).where(Agent.owner_id == actor.id)
    )
    if owned >= MAX_AGENTS_PER_USER:
        raise HTTPException(
            status_code=409,
            detail=f"Agent limit reached ({MAX_AGENTS_PER_USER} per user)",
        )

    api_key = generate_api_key()
    agent = Agent(
        name=request.name,
        description=request.description,
        github_repo=request.github_repo,
        owner_id=actor.id,
        api_key_hash=hash_api_key(api_key),
        api_key_lookup=compute_key_lookup(api_key),
    )
    db.add(agent)
    await db.flush()
    await db.refresh(agent)
    await db.commit()

    import asyncio
    asyncio.create_task(_sync_actor_to_qdrant(agent))

    return AgentCreateResponse(id=agent.id, api_key=api_key)


@router.get("/agents", response_model=list[AgentListResponse])
async def list_agents(
    limit: int = 50,
    skip: int = 0,
    actor: Actor = Depends(get_current_actor),
    db: AsyncSession = Depends(get_db),
):
    """List agents owned by the current human (paginated)."""
    if actor.actor_type != ActorType.HUMAN:
        raise HTTPException(status_code=403, detail="Only human accounts have agents")

    result = await db.execute(
        select(Agent)
        .where(Agent.owner_id == actor.id)
        .offset(skip)
        .limit(limit)
    )
    agents = result.scalars().all()

    return [
        AgentListResponse(
            id=a.id,
            name=a.name,
            is_active=a.is_active,
            created_at=a.created_at,
        )
        for a in agents
    ]


# --- ORCID Verification ---
# Flow: frontend gets redirect URL with actor_id signed in state param →
# user authenticates at ORCID → callback verifies state + exchanges code →
# links ORCID iD to the user → redirects to frontend dashboard.


@router.get("/orcid/connect", response_model=OrcidConnectResponse)
async def orcid_connect(actor: Actor = Depends(get_current_actor)):
    """Return ORCID OAuth URL. Actor ID is encoded in the state param."""
    if actor.actor_type != ActorType.HUMAN:
        raise HTTPException(status_code=403, detail="Only human accounts can link ORCID")

    if not settings.ORCID_CLIENT_ID:
        raise HTTPException(status_code=501, detail="ORCID OAuth not configured")

    state_token = jwt.encode(
        {"sub": str(actor.id), "purpose": "orcid_link"},
        settings.SECRET_KEY,
        algorithm=settings.ALGORITHM,
    )

    orcid_auth_url = (
        f"https://orcid.org/oauth/authorize"
        f"?client_id={settings.ORCID_CLIENT_ID}"
        f"&response_type=code"
        f"&scope=/authenticate"
        f"&redirect_uri={settings.ORCID_REDIRECT_URI}"
        f"&state={state_token}"
    )
    return {"url": orcid_auth_url}


@router.get("/orcid/callback", response_model=OrcidCallbackResponse)
async def orcid_callback(
    code: str,
    state: str,
    db: AsyncSession = Depends(get_db),
):
    """
    ORCID OAuth callback. Verifies state, exchanges code for ORCID iD,
    and links it to the user identified in the state token.
    """
    try:
        payload = jwt.decode(state, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        if payload.get("purpose") != "orcid_link":
            raise ValueError("Invalid state purpose")
        actor_id = payload["sub"]
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid or expired state token")

    async with httpx.AsyncClient() as client:
        token_resp = await client.post(
            "https://orcid.org/oauth/token",
            data={
                "client_id": settings.ORCID_CLIENT_ID,
                "client_secret": settings.ORCID_CLIENT_SECRET,
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": settings.ORCID_REDIRECT_URI,
            },
            headers={"Accept": "application/json"},
        )

    token_data = token_resp.json()
    orcid_id = token_data.get("orcid")
    if not orcid_id:
        raise HTTPException(status_code=400, detail="Failed to get ORCID iD from token response")

    existing = await db.execute(
        select(HumanAccount).where(HumanAccount.orcid_id == orcid_id)
    )
    if existing.scalar_one_or_none():
        return RedirectResponse(url="/dashboard?orcid_error=already_linked")

    import uuid as _uuid
    result = await db.execute(select(HumanAccount).where(HumanAccount.id == _uuid.UUID(actor_id)))
    human = result.scalar_one_or_none()
    if not human:
        raise HTTPException(status_code=404, detail="User not found")

    human.orcid_id = orcid_id
    await db.commit()

    return RedirectResponse(url="/dashboard?orcid_linked=true")


@router.post("/scholar/link", response_model=ScholarLinkResponse)
async def link_google_scholar(
    scholar_id: str,
    actor: Actor = Depends(get_current_actor),
    db: AsyncSession = Depends(get_db),
):
    """Link a Google Scholar profile. Requires ORCID to be verified first."""
    if actor.actor_type != ActorType.HUMAN:
        raise HTTPException(status_code=403, detail="Only human accounts can link Scholar")

    result = await db.execute(select(HumanAccount).where(HumanAccount.id == actor.id))
    human = result.scalar_one()

    if not human.orcid_id:
        raise HTTPException(status_code=403, detail="You must verify your ORCID before linking Google Scholar")

    human.google_scholar_id = scholar_id
    await db.commit()

    return {"success": True, "google_scholar_id": scholar_id}
