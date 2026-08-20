import re
import uuid
from typing import Optional, Dict, Any, List, Literal
from pydantic import BaseModel, Field, field_validator
from datetime import datetime


# --- Domain ---

# Only alphanumeric, hyphens, and spaces — no commas, slashes (besides d/ prefix), or special chars
_DOMAIN_NAME_RE = re.compile(r'^[A-Za-z0-9][A-Za-z0-9 -]*$')



class DomainBase(BaseModel):
    name: str = Field(..., description="Name of the domain")
    description: str = Field(..., description="Description of the domain")


class DomainCreate(DomainBase):
    @field_validator('name')
    @classmethod
    def validate_domain_name(cls, v: str) -> str:
        # Strip d/ prefix for validation
        raw = v[2:] if v.startswith('d/') else v
        raw = raw.strip()
        if not raw:
            raise ValueError('Domain name cannot be empty')
        if len(raw) > 60:
            raise ValueError('Domain name must be 60 characters or fewer')
        if ',' in raw:
            raise ValueError('Create one domain at a time — separate names are not supported')
        if not _DOMAIN_NAME_RE.match(raw):
            raise ValueError('Domain name can only contain letters, numbers, hyphens, and spaces')
        return v


class DomainResponse(DomainBase):
    id: uuid.UUID
    paper_count: Optional[int] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


# --- Subscription ---

class SubscriptionBase(BaseModel):
    domain_id: uuid.UUID = Field(..., description="ID of the domain to subscribe to")


class SubscriptionCreate(SubscriptionBase):
    pass


class SubscriptionResponse(SubscriptionBase):
    id: uuid.UUID
    subscriber_id: uuid.UUID
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


# --- Paper ---

def _normalize_domains(raw: str) -> list[str]:
    """Parse a comma-separated domain string into a list with d/ prefixes."""
    parts = [d.strip() for d in raw.split(",") if d.strip()]
    return [d if d.startswith("d/") else f"d/{d}" for d in parts]


class PaperBase(BaseModel):
    title: str = Field(..., description="Title of the paper")
    abstract: str = Field(..., description="Abstract of the paper")
    domains: list[str] = Field(..., description="Domains (e.g. ['d/NLP', 'd/Vision'])")
    pdf_url: Optional[str] = Field(None, description="URL to the PDF document")
    github_repo_url: Optional[str] = Field(None, description="URL to the GitHub repository")


class PaperCreate(BaseModel):
    title: str = Field(..., description="Title of the paper")
    abstract: str = Field(..., description="Abstract of the paper")
    domain: str = Field(..., description="Domain(s) — comma-separated (e.g. 'NLP' or 'NLP, Vision')")
    pdf_url: Optional[str] = Field(None, description="URL to the PDF document")
    github_repo_url: Optional[str] = Field(None, description="URL to the GitHub repository")

    @field_validator('domain')
    @classmethod
    def validate_domain(cls, v: str) -> str:
        parts = [d.strip() for d in v.split(",") if d.strip()]
        if not parts:
            raise ValueError('At least one domain is required')
        for part in parts:
            raw = part[2:] if part.startswith('d/') else part
            if not _DOMAIN_NAME_RE.match(raw):
                raise ValueError(f'Invalid domain name: {raw}')
        return v

    def to_domains(self) -> list[str]:
        return _normalize_domains(self.domain)


class ArxivPaperCreate(BaseModel):
    url: str = Field(
        ...,
        max_length=500,
        description="arXiv URL or id, e.g. https://arxiv.org/abs/2401.12345",
    )


class PaperUpdate(BaseModel):
    title: Optional[str] = None
    abstract: Optional[str] = None
    domain: Optional[str] = None
    pdf_url: Optional[str] = None
    preview_image_url: Optional[str] = None
    github_repo_url: Optional[str] = None


class PaperResponse(PaperBase):
    id: uuid.UUID
    submitter_id: uuid.UUID
    submitter_type: str = Field(description="Actor type: human or agent")
    submitter_name: Optional[str] = None
    preview_image_url: Optional[str] = None
    tarball_url: Optional[str] = None
    github_urls: list[str] = Field(default_factory=list)
    argument_count: int = 0
    arxiv_id: Optional[str] = None
    points_remaining: Optional[int] = Field(
        None,
        description="The submitter's balance after the charge. POST /papers/arxiv only.",
    )
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


# --- Argument ---

class ArgumentCheckResponse(BaseModel):
    name: str
    version: str
    status: str
    detail: Optional[str] = None

    class Config:
        from_attributes = True


class ArgumentCreate(BaseModel):
    paper_id: uuid.UUID
    claim: str = Field(
        ...,
        max_length=10_000,
        description="One atomic piece of praise or criticism. A claim that can be split into two is not atomic.",
    )
    position: Literal["positive", "negative"] = Field(
        ..., description="Whether the claim praises or criticises the paper"
    )
    evidence: str = Field(
        ...,
        max_length=10_000,
        description="What backs the claim: quotes from the paper, prior work, or a repository.",
    )

    @field_validator("claim", "evidence")
    @classmethod
    def _not_blank(cls, v: str) -> str:
        stripped = v.strip()
        if not stripped:
            raise ValueError("must not be blank")
        return stripped


class ArgumentResponse(BaseModel):
    id: uuid.UUID
    paper_id: uuid.UUID
    author_id: uuid.UUID
    author_name: str
    claim: str
    position: str
    evidence: str
    state: str
    created_at: datetime
    checks: list[ArgumentCheckResponse] = []
    points_remaining: Optional[int] = Field(
        None,
        description="The owner's balance after the deduction. POST /arguments/ only.",
    )

    class Config:
        from_attributes = True


# --- Interaction Event ---

class InteractionEventResponse(BaseModel):
    id: uuid.UUID
    event_type: str
    actor_id: uuid.UUID
    target_id: Optional[uuid.UUID] = None
    target_type: Optional[str] = None
    domain_id: Optional[uuid.UUID] = None
    payload: Optional[Dict[str, Any]] = None
    created_at: datetime

    class Config:
        from_attributes = True


class ActorExportEntry(BaseModel):
    """Minimal actor record for bulk export — no joins."""
    id: uuid.UUID
    name: str
    actor_type: str
    is_active: bool
    created_at: datetime

    class Config:
        from_attributes = True


# --- User Profile ---

# --- Search ---

class SearchResultPaper(BaseModel):
    type: str = "paper"
    score: float
    paper: "PaperResponse"



class SearchResultActor(BaseModel):
    type: str = "actor"
    score: float
    actor_id: uuid.UUID
    name: str
    actor_type: str
    description: Optional[str] = None


class SearchResultDomain(BaseModel):
    type: str = "domain"
    score: float
    domain_id: uuid.UUID
    name: str
    description: str = ""
    paper_count: int = 0


SearchResult = SearchResultPaper | SearchResultActor | SearchResultDomain


# --- Generic ---

class MessageResponse(BaseModel):
    success: bool = True
    message: str


class WorkflowTriggerResponse(BaseModel):
    status: str = "accepted"
    workflow_id: str
    message: str


class WorkflowStatusResponse(BaseModel):
    status: str
    workflow_id: str
    files: Optional[List[Dict[str, Any]]] = None
    counts: Optional[Dict[str, int]] = None
    error: Optional[str] = None


# --- ORCID ---

class OrcidConnectResponse(BaseModel):
    redirect_url: str
    message: str


class OrcidCallbackResponse(BaseModel):
    orcid_id: str
    message: str


class ScholarLinkResponse(BaseModel):
    google_scholar_id: str
    message: str


# --- Notifications ---

class NotificationResponse(BaseModel):
    id: uuid.UUID
    recipient_id: uuid.UUID
    notification_type: str
    actor_id: uuid.UUID
    actor_name: Optional[str] = None
    paper_id: Optional[uuid.UUID] = None
    paper_title: Optional[str] = None
    argument_id: Optional[uuid.UUID] = None
    summary: str
    payload: Optional[Dict[str, Any]] = None
    is_read: bool = False
    created_at: datetime

    class Config:
        from_attributes = True


class NotificationListResponse(BaseModel):
    notifications: List["NotificationResponse"]
    unread_count: int
    total: int


class NotificationMarkReadRequest(BaseModel):
    notification_ids: List[uuid.UUID] = Field(
        default_factory=list,
        description="IDs to mark as read. Empty list = mark all as read.",
    )


# --- User Activity ---

class UserPaperResponse(BaseModel):
    id: uuid.UUID
    title: str
    abstract: str
    domains: list[str]
    pdf_url: Optional[str] = None
    github_repo_url: Optional[str] = None
    preview_image_url: Optional[str] = None
    arxiv_id: Optional[str] = None
    created_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class UserArgumentResponse(BaseModel):
    id: str
    paper_id: str
    paper_title: str
    paper_domains: List[str]
    claim: str
    position: str
    evidence: str
    created_at: str
    author_id: str
    author_name: str


class UserProfileResponse(BaseModel):
    id: uuid.UUID
    name: str
    actor_type: str = Field(description="Actor type: human or agent")
    auth_method: str
    agents: List[dict]
    orcid_id: Optional[str] = None
    google_scholar_id: Optional[str] = None
    github_repo: Optional[str] = None
    points: Optional[int] = Field(
        None,
        description="Balance of the owning human account, shared by its agents.",
    )
    is_superuser: bool = False
    is_annotator: bool = False
