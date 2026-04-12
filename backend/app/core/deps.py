"""
FastAPI dependencies for authentication and database sessions.
"""
import uuid

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.core.security import decode_token, verify_api_key, compute_key_lookup
from app.models.identity import Actor, HumanAccount, DelegatedAgent, ActorType

http_bearer = HTTPBearer(auto_error=False)


def _extract_token(request: Request, credentials: HTTPAuthorizationCredentials | None) -> str | None:
    """Extract token from Authorization header, supporting both 'Bearer <token>' and raw '<token>'."""
    if credentials is not None:
        return credentials.credentials
    # Fallback: read raw Authorization header (no Bearer prefix)
    auth = request.headers.get("authorization")
    if auth:
        return auth.removeprefix("Bearer ").strip()
    return None


async def get_current_actor(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(http_bearer),
    db: AsyncSession = Depends(get_db),
) -> Actor:
    """
    Resolve the current actor from either:
    1. JWT Bearer token (for humans via OAuth)
    2. API key (for delegated agents, prefixed with 'cs_')

    Accepts both 'Authorization: Bearer <token>' and 'Authorization: <token>'.
    """
    token = _extract_token(request, credentials)

    if token is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Check if it's an API key (delegated agent auth)
    if token.startswith("cs_"):
        return await _resolve_api_key_actor(token, db)

    # Otherwise treat as JWT
    return await _resolve_jwt_actor(token, db)


async def require_superuser(
    actor: Actor = Depends(get_current_actor),
    db: AsyncSession = Depends(get_db),
) -> Actor:
    """Dependency that requires the current actor to be a superuser human account."""
    if actor.actor_type != ActorType.HUMAN:
        raise HTTPException(status_code=403, detail="Superuser access required")
    result = await db.execute(select(HumanAccount).where(HumanAccount.id == actor.id))
    human = result.scalar_one_or_none()
    if not human or not human.is_superuser:
        raise HTTPException(status_code=403, detail="Superuser access required")
    return actor


async def get_current_actor_optional(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(http_bearer),
    db: AsyncSession = Depends(get_db),
) -> Actor | None:
    """Same as get_current_actor but returns None for unauthenticated requests."""
    token = _extract_token(request, credentials)
    if token is None:
        return None

    try:
        return await get_current_actor(request, credentials, db)
    except HTTPException:
        return None


async def _resolve_jwt_actor(token: str, db: AsyncSession) -> Actor:
    payload = decode_token(token)
    if payload is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
        )

    actor_id = payload.get("sub")
    if actor_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token payload",
        )

    result = await db.execute(select(Actor).where(Actor.id == uuid.UUID(actor_id)))
    actor = result.scalar_one_or_none()

    if actor is None or not actor.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Actor not found or inactive",
        )

    return actor


async def _resolve_api_key_actor(api_key: str, db: AsyncSession) -> Actor:
    """
    Resolve a delegated agent by API key in O(1):
    1. Compute SHA256 of the key for fast indexed lookup
    2. Verify the match with bcrypt (salted hash)
    """
    lookup_hash = compute_key_lookup(api_key)

    result = await db.execute(
        select(DelegatedAgent).where(DelegatedAgent.api_key_lookup == lookup_hash)
    )
    agent = result.scalar_one_or_none()

    if agent is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API key",
        )

    # Verify with bcrypt (guards against SHA256 collision, however unlikely)
    if not verify_api_key(api_key, agent.api_key_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API key",
        )

    if not agent.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Agent has been deactivated by its owner",
        )

    return agent
