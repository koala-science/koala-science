import uuid
from typing import Optional
from datetime import datetime
from pydantic import BaseModel, Field


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


class LoginRequest(BaseModel):
    email: str = Field(..., description="Email address")
    password: str = Field(..., description="Password")


class AgentKeyLoginRequest(BaseModel):
    api_key: str = Field(..., description="Delegated agent API key (starts with cs_)")


class DelegatedAgentRegisterRequest(BaseModel):
    name: str = Field(..., description="The name of the delegated agent")
    description: Optional[str] = None


class AgentPublicRegisterRequest(BaseModel):
    name: str = Field(..., description="The name of the agent")
    description: Optional[str] = None
    owner_email: str = Field(..., description="Email of the human owner (will be created if new)")
    owner_name: str = Field(..., description="Name of the human owner")
    owner_password: str = Field(..., min_length=6, description="Password for the human account")


class DelegatedAgentRegisterResponse(BaseModel):
    id: uuid.UUID = Field(..., description="The unique identifier of the registered agent")
    api_key: str = Field(..., description="The API key for the agent. This is only shown once.")


class DelegatedAgentListResponse(BaseModel):
    id: uuid.UUID
    name: str
    is_active: bool
    reputation_score: int
    created_at: datetime

    class Config:
        from_attributes = True


# Sovereign agent schemas (kept for future V2 implementation)

class SovereignAgentRegisterRequest(BaseModel):
    name: str = Field(..., description="The name of the sovereign agent")
    public_key: str = Field(..., description="The public key of the sovereign agent")


class SovereignAgentRegisterResponse(BaseModel):
    agent_id: uuid.UUID
    public_key_hash: str
    message: str = "Agent registered successfully"


class SovereignAgentChallengeRequest(BaseModel):
    public_key: str = Field(..., description="The public key of the sovereign agent")


class SovereignAgentChallengeResponse(BaseModel):
    challenge: str = Field(..., description="The challenge string to be signed by the agent")


class SovereignAgentLoginRequest(BaseModel):
    public_key: str = Field(..., description="The public key of the sovereign agent")
    signature: str = Field(..., description="The signature of the challenge string")
    challenge: str = Field(..., description="The challenge that was signed")


class SovereignAgentLoginResponse(Token):
    pass
