"""
Authentication endpoints:
- Email/password signup and login (for humans)
- Delegated agent API key registration and management
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
from app.models.identity import Actor, ActorType, HumanAccount, DelegatedAgent
from app.schemas.auth import (
    SignupRequest,
    LoginRequest,
    AgentKeyLoginRequest,
    DelegatedAgentRegisterRequest,
    AgentPublicRegisterRequest,
    DelegatedAgentRegisterResponse,
    DelegatedAgentListResponse,
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
    # Check if email already exists
    existing = await db.execute(
        select(HumanAccount).where(HumanAccount.email == request.email)
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="An account with this email already exists")

    user = HumanAccount(
        name=request.name,
        email=request.email,
        hashed_password=hash_password(request.password),
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
    Login as a delegated agent using an API key.
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


# --- Agent Registration (public, but requires owner identity) ---


@router.post(
    "/agents/register",
    response_model=DelegatedAgentRegisterResponse,
    status_code=status.HTTP_201_CREATED,
)
async def register_agent(
    request: AgentPublicRegisterRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    Register an agent with a human owner. No auth required, but owner_email
    and owner_name are mandatory. If the email doesn't match an existing
    human account, one is created automatically (no password — login via
    the dashboard to set one later).
    """
    # Find or create the human owner
    result = await db.execute(
        select(HumanAccount).where(HumanAccount.email == request.owner_email)
    )
    owner = result.scalar_one_or_none()

    if not owner:
        owner = HumanAccount(
            name=request.owner_name,
            email=request.owner_email,
        )
        db.add(owner)
        await db.flush()
        await db.refresh(owner)

    api_key = generate_api_key()
    agent = DelegatedAgent(
        name=request.name,
        description=request.description,
        owner_id=owner.id,
        api_key_hash=hash_api_key(api_key),
        api_key_lookup=compute_key_lookup(api_key),
        api_key_plain=api_key,
    )
    db.add(agent)
    await db.flush()
    await db.refresh(agent)
    await db.commit()

    return DelegatedAgentRegisterResponse(id=agent.id, api_key=api_key)


# --- Delegated Agent Management (authenticated) ---


@router.post(
    "/agents/delegated/register",
    response_model=DelegatedAgentRegisterResponse,
    status_code=status.HTTP_201_CREATED,
)
async def register_delegated_agent(
    request: DelegatedAgentRegisterRequest,
    actor: Actor = Depends(get_current_actor),
    db: AsyncSession = Depends(get_db),
):
    """
    Register a new delegated agent under the authenticated human account.
    Returns the API key — shown only once.
    """
    if actor.actor_type != ActorType.HUMAN:
        raise HTTPException(
            status_code=403, detail="Only human accounts can register delegated agents"
        )

    api_key = generate_api_key()
    agent = DelegatedAgent(
        name=request.name,
        description=request.description,
        owner_id=actor.id,
        api_key_hash=hash_api_key(api_key),
        api_key_lookup=compute_key_lookup(api_key),
        api_key_plain=api_key,
    )
    db.add(agent)
    await db.flush()
    await db.refresh(agent)
    await db.commit()

    return DelegatedAgentRegisterResponse(id=agent.id, api_key=api_key)


@router.get("/agents/delegated", response_model=list[DelegatedAgentListResponse])
async def list_delegated_agents(
    limit: int = 50,
    skip: int = 0,
    actor: Actor = Depends(get_current_actor),
    db: AsyncSession = Depends(get_db),
):
    """List delegated agents owned by the current human (paginated)."""
    if actor.actor_type != ActorType.HUMAN:
        raise HTTPException(status_code=403, detail="Only human accounts have delegated agents")

    result = await db.execute(
        select(DelegatedAgent)
        .where(DelegatedAgent.owner_id == actor.id)
        .offset(skip)
        .limit(limit)
    )
    agents = result.scalars().all()

    return [
        DelegatedAgentListResponse(
            id=a.id,
            name=a.name,
            is_active=a.is_active,
            reputation_score=a.reputation_score,
            created_at=a.created_at,
        )
        for a in agents
    ]


@router.delete("/agents/delegated/{agent_id}", response_model=MessageResponse)
async def revoke_delegated_agent(
    agent_id: str,
    actor: Actor = Depends(get_current_actor),
    db: AsyncSession = Depends(get_db),
):
    """Kill switch: deactivate a delegated agent."""
    if actor.actor_type != ActorType.HUMAN:
        raise HTTPException(status_code=403, detail="Only human accounts can manage agents")

    result = await db.execute(
        select(DelegatedAgent).where(
            DelegatedAgent.id == agent_id,
            DelegatedAgent.owner_id == actor.id,
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

    # Sign the actor_id into state so callback knows who initiated
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
    # Return URL instead of redirect — frontend opens it (preserves JWT context)
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
    # Verify state token to identify which user initiated this
    try:
        payload = jwt.decode(state, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        if payload.get("purpose") != "orcid_link":
            raise ValueError("Invalid state purpose")
        actor_id = payload["sub"]
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid or expired state token")

    # Exchange code for token + ORCID iD
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

    # Check if this ORCID is already linked to another account
    existing = await db.execute(
        select(HumanAccount).where(HumanAccount.orcid_id == orcid_id)
    )
    if existing.scalar_one_or_none():
        # Redirect to dashboard with error
        return RedirectResponse(url="/dashboard?orcid_error=already_linked")

    # Link ORCID to the user
    import uuid as _uuid
    result = await db.execute(select(HumanAccount).where(HumanAccount.id == _uuid.UUID(actor_id)))
    human = result.scalar_one_or_none()
    if not human:
        raise HTTPException(status_code=404, detail="User not found")

    human.orcid_id = orcid_id
    await db.commit()

    # Redirect to dashboard with success
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

    # Must have ORCID verified first
    result = await db.execute(select(HumanAccount).where(HumanAccount.id == actor.id))
    human = result.scalar_one()

    if not human.orcid_id:
        raise HTTPException(status_code=403, detail="You must verify your ORCID before linking Google Scholar")

    human.google_scholar_id = scholar_id
    await db.commit()

    return {"success": True, "google_scholar_id": scholar_id}
