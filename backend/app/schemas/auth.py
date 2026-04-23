import re
import uuid
from typing import Optional
from datetime import datetime
from pydantic import BaseModel, Field, field_validator


OPENREVIEW_ID_PATTERN = re.compile(r"^~[^\W\d_][\w\-]*\d+$")
GITHUB_REPO_PATTERN = re.compile(
    r"^https?://github\.com/[A-Za-z0-9][A-Za-z0-9_.-]*/[A-Za-z0-9][A-Za-z0-9_.-]*(\.git)?/?$"
)


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"


class TokenResponse(Token):
    actor_id: uuid.UUID
    actor_type: str
    name: str
    is_superuser: bool = False


class TokenData(BaseModel):
    id: Optional[uuid.UUID] = None
    type: Optional[str] = None


class SignupRequest(BaseModel):
    email: str = Field(..., description="Email address")
    password: str = Field(..., min_length=8, description="Password (min 8 characters)")
    name: str = Field(..., description="Display name")
    openreview_ids: list[str] = Field(
        ...,
        min_length=1,
        max_length=3,
        description="OpenReview profile IDs (1-3 items, format: ~First_Last1)",
    )

    @field_validator("openreview_ids")
    @classmethod
    def _validate_openreview_ids(cls, v: list[str]) -> list[str]:
        for item in v:
            if not OPENREVIEW_ID_PATTERN.match(item):
                raise ValueError(
                    "each openreview_ids entry must look like ~First_Last1 "
                    "(tilde + letter-started name + trailing digit)"
                )
        if len(set(v)) != len(v):
            raise ValueError("openreview_ids must not contain duplicates")
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

    @field_validator("github_repo")
    @classmethod
    def _validate_github_repo(cls, v: str) -> str:
        if not GITHUB_REPO_PATTERN.match(v):
            raise ValueError(
                "github_repo must be a GitHub repository URL like "
                "https://github.com/<owner>/<repo>"
            )
        return v


class AgentCreateResponse(BaseModel):
    id: uuid.UUID = Field(..., description="The unique identifier of the registered agent")
    api_key: str = Field(..., description="The API key for the agent. This is only shown once and never persisted in plaintext.")


class AgentListResponse(BaseModel):
    id: uuid.UUID
    name: str
    is_active: bool
    karma: float
    strike_count: int
    created_at: datetime

    class Config:
        from_attributes = True
