import re
import uuid
from typing import Optional
from datetime import datetime
from pydantic import BaseModel, ConfigDict, Field, field_validator


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
    is_annotator: bool = False


class TokenData(BaseModel):
    id: Optional[uuid.UUID] = None
    type: Optional[str] = None


# The address is what the OpenReview claim rests on, so it has to parse before
# any domain check sees it: `rpartition("@")` on a string with no "@" returns the
# whole string as the domain, which would clear both the free-mail gate and the
# profile match. Stored lowercase because the unique index is case-sensitive and
# two casings of one address must not be two accounts.
EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s.]+$")


def normalized_email(value: str) -> str:
    email = value.strip().lower()
    if not EMAIL_PATTERN.match(email):
        raise ValueError("Enter a valid email address")
    return email


class SignupRequest(BaseModel):
    """Signup asks only what is needed to send the link.

    No password and no display name: both are set by whoever redeems the link, so
    that a signup posted for someone else's address cannot decide who owns the
    account that address ends up with.
    """

    model_config = ConfigDict(extra="forbid")

    email: str = Field(..., max_length=254, description="Email address")
    openreview_id: str = Field(
        ...,
        description="OpenReview profile ID (format: ~First_Last1)",
    )

    @field_validator("email")
    @classmethod
    def _normalize_email(cls, v: str) -> str:
        return normalized_email(v)

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
    email: str = Field(..., max_length=254, description="Email address")
    password: str = Field(..., description="Password")

    @field_validator("email")
    @classmethod
    def _lowercase(cls, v: str) -> str:
        """Lowercased to match how signup stores it.

        Not validated: a malformed address here should fail to match and return
        401, not tell an unauthenticated caller their input was the wrong shape.
        """
        return v.strip().lower()


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
    created_at: datetime

    class Config:
        from_attributes = True


class VerifyEmailRequest(BaseModel):
    token: str = Field(..., max_length=200, description="The token from the verification link")
    name: str = Field(..., min_length=1, max_length=200, description="Display name")
    password: str = Field(..., min_length=8, max_length=200, description="Password")


class ResendVerificationRequest(BaseModel):
    email: str = Field(..., max_length=254, description="Address to resend the verification link to")

    @field_validator("email")
    @classmethod
    def _normalize_email(cls, v: str) -> str:
        return normalized_email(v)


class SignupResponse(BaseModel):
    """Signup issues no tokens: the account cannot act until its address is proven."""

    verification_required: bool
    email: str
