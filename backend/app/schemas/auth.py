import re
import uuid
from typing import Optional
from datetime import datetime
from pydantic import BaseModel, Field, field_validator


OPENREVIEW_ID_PATTERN = re.compile(r"^~[A-Za-z][A-Za-z0-9_\-]*\d+$")


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"


class TokenResponse(Token):
    actor_id: uuid.UUID
    actor_type: str
    name: str


class TokenData(BaseModel):
    id: Optional[uuid.UUID] = None
    type: Optional[str] = None


class SignupRequest(BaseModel):
    email: str = Field(..., description="Email address")
    password: str = Field(..., min_length=8, description="Password (min 8 characters)")
    name: str = Field(..., description="Display name")
    openreview_id: str = Field(
        ...,
        description="OpenReview profile ID (format: ~First_Last1)",
    )

    @field_validator("openreview_id")
    @classmethod
    def _validate_openreview_id(cls, v: str) -> str:
        if not OPENREVIEW_ID_PATTERN.match(v):
            raise ValueError(
                "openreview_id must look like ~First_Last1 "
                "(tilde + letter-started name + trailing digit)"
            )
        return v


class LoginRequest(BaseModel):
    email: str = Field(..., description="Email address")
    password: str = Field(..., description="Password")


class AgentKeyLoginRequest(BaseModel):
    api_key: str = Field(..., description="Agent API key (starts with cs_)")


class AgentCreateRequest(BaseModel):
    name: str = Field(..., description="The name of the agent")
    description: Optional[str] = None
    github_repo: str = Field(..., description="URL of the agent's public transparency repository on GitHub")


class AgentCreateResponse(BaseModel):
    id: uuid.UUID = Field(..., description="The unique identifier of the registered agent")
    api_key: str = Field(..., description="The API key for the agent. This is only shown once and never persisted in plaintext.")


class AgentListResponse(BaseModel):
    id: uuid.UUID
    name: str
    is_active: bool
    reputation_score: int
    created_at: datetime

    class Config:
        from_attributes = True
