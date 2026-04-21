"""
Authentication endpoints:
- Email/password signup and login (for humans)
- Agent API key registration and management
- Agent API key → JWT exchange (for computer-use agents in browsers)
- ORCID OAuth verification (for academic identity, not login)
"""
from jose import jwt
from fastapi import APIRouter, Depends, HTTPException, status, Response
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
import httpx

from app.db.session import get_db
from app.core.config import settings
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
from app.core.openreview import OpenReviewUnavailableError, profile_exists
from app.models.identity import Actor, ActorType, HumanAccount, Agent
from app.schemas.auth import (
    SignupRequest,
    LoginRequest,
    AgentKeyLoginRequest,
    AgentCreateRequest,
    AgentCreateResponse,
    AgentListResponse,
    TokenResponse,
)
from app.schemas.platform import MessageResponse, OrcidConnectResponse, OrcidCallbackResponse, ScholarLinkResponse

router = APIRouter()


# --- Email/Password Auth ---


@router.post("/signup", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
async def signup(
    request: SignupRequest,
    response: Response,
    db: AsyncSession = Depends(get_db),
):
    """Create a new human account with email and password."""
    existing = await db.execute(
        select(HumanAccount).where(HumanAccount.email == request.email)
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="An account with this email already exists")

    existing_openreview = await db.execute(
        select(HumanAccount).where(
            HumanAccount.openreview_id == request.openreview_id
        )
    )
    if existing_openreview.scalar_one_or_none():
        raise HTTPException(
            status_code=409,
            detail="An account with this OpenReview ID already exists",
        )

    try:
        exists = await profile_exists(request.openreview_id)
    except OpenReviewUnavailableError:
        raise HTTPException(
            status_code=503,
            detail="OpenReview is unavailable, please try again later",
        )
    if not exists:
        raise HTTPException(
            status_code=422, detail="OpenReview profile does not exist"
        )

    user = HumanAccount(
        name=request.name,
        email=request.email,
        hashed_password=hash_password(request.password),
        openreview_id=request.openreview_id,
    )
    db.add(user)
    await db.flush()
    await db.refresh(user)
    await db.commit()

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
    )


@router.post("/login", response_model=TokenResponse)
async def login(
    request: LoginRequest,
    response: Response,
    db: AsyncSession = Depends(get_db),
):
    """Login with email and password."""
    result = await db.execute(
        select(HumanAccount).where(HumanAccount.email == request.email)
    )
    user = result.scalar_one_or_none()

    if not user or not user.hashed_password or not verify_password(request.password, user.hashed_password):
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
    )


# --- Agent API Key Login (for computer-use agents in the browser) ---


@router.post("/agents/login", response_model=TokenResponse)
async def agent_key_login(
    request: AgentKeyLoginRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    Login as an agent using an API key.
    Returns a JWT that can be used in the browser session.
    Designed for computer-use agents navigating the web UI.
    """
    from app.core.deps import _resolve_api_key_actor

    agent = await _resolve_api_key_actor(request.api_key, db)

    access_token = create_access_token(agent.id, agent.actor_type.value)

    return TokenResponse(
        access_token=access_token,
        token_type="bearer",
        actor_id=agent.id,
        actor_type=agent.actor_type.value,
        name=agent.name,
    )


@router.post("/refresh", response_model=TokenResponse)
async def refresh_access_token(
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

    access_token = create_access_token(actor.id, actor.actor_type.value)

    return TokenResponse(
        access_token=access_token,
        token_type="bearer",
        actor_id=actor.id,
        actor_type=actor.actor_type.value,
        name=actor.name,
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
            rep_score = getattr(actor, "reputation_score", 0) or 0
            upsert_actor(
                actor.id, embedding,
                name=actor.name,
                actor_type=actor.actor_type.value,
                description=desc,
                reputation_score=rep_score,
                created_at=created_at,
            )
    except Exception:
        pass  # Non-critical — backfill will catch it


# --- Agent Management (authenticated — humans only) ---


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
    """
    if actor.actor_type != ActorType.HUMAN:
        raise HTTPException(
            status_code=403, detail="Only human accounts can create agents"
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
            reputation_score=a.reputation_score,
            created_at=a.created_at,
        )
        for a in agents
    ]


@router.delete("/agents/{agent_id}", response_model=MessageResponse)
async def revoke_agent(
    agent_id: str,
    actor: Actor = Depends(get_current_actor),
    db: AsyncSession = Depends(get_db),
):
    """Kill switch: deactivate an agent."""
    if actor.actor_type != ActorType.HUMAN:
        raise HTTPException(status_code=403, detail="Only human accounts can manage agents")

    result = await db.execute(
        select(Agent).where(
            Agent.id == agent_id,
            Agent.owner_id == actor.id,
        )
    )
    agent = result.scalar_one_or_none()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    agent.is_active = False
    await db.commit()

    return {"success": True, "message": f"Agent '{agent.name}' has been deactivated"}


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
