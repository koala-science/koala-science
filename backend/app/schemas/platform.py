import re
import uuid
from typing import Optional, Dict, Any, List
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


class PaperUpdate(BaseModel):
    title: Optional[str] = None
    abstract: Optional[str] = None
    domain: Optional[str] = None
    pdf_url: Optional[str] = None
    preview_image_url: Optional[str] = None
    github_repo_url: Optional[str] = None


class PaperIngest(BaseModel):
    arxiv_url: str = Field(..., description="arXiv URL or ID to ingest")
    domain: Optional[str] = Field(None, description="Override domain assignment (comma-separated for multiple)")

    def to_domains(self) -> list[str]:
        if self.domain:
            return _normalize_domains(self.domain)
        return []


class PaperResponse(PaperBase):
    id: uuid.UUID
    submitter_id: uuid.UUID
    submitter_type: str = Field(description="Actor type: human, delegated_agent, sovereign_agent")
    submitter_name: Optional[str] = None
    preview_image_url: Optional[str] = None
    comment_count: int = 0
    upvotes: int = 0
    downvotes: int = 0
    net_score: int = 0
    arxiv_id: Optional[str] = None
    current_version: int = Field(1, description="Latest revision version number")
    revision_count: int = Field(1, description="Total number of revisions")
    latest_revision: Optional["PaperRevisionResponse"] = Field(
        None, description="Latest revision details (title, abstract, changelog, etc.)"
    )
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


# --- Verdict ---

class VerdictCreate(BaseModel):
    paper_id: uuid.UUID
    content_markdown: str = Field(..., min_length=1, description="Written assessment in markdown")
    score: float = Field(..., ge=0, le=10, description="Score from 0 (reject) to 10 (strong accept)")


class VerdictResponse(BaseModel):
    id: uuid.UUID
    paper_id: uuid.UUID
    author_id: uuid.UUID
    author_type: str
    author_name: Optional[str] = None
    content_markdown: str
    score: float
    upvotes: int = 0
    downvotes: int = 0
    net_score: int = 0
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


# --- Paper Revision ---

class PaperRevisionBase(BaseModel):
    title: str = Field(..., description="Title for this revision")
    abstract: str = Field(..., description="Abstract for this revision")
    pdf_url: Optional[str] = Field(None, description="URL to the PDF document")
    github_repo_url: Optional[str] = Field(None, description="URL to the GitHub repository")
    changelog: Optional[str] = Field(None, description="Optional summary of what changed")


class PaperRevisionCreate(PaperRevisionBase):
    pass


class PaperRevisionResponse(PaperRevisionBase):
    id: uuid.UUID
    paper_id: uuid.UUID
    version: int
    created_by_id: uuid.UUID
    created_by_type: str = Field(description="Actor type: human, delegated_agent, sovereign_agent")
    created_by_name: Optional[str] = None
    preview_image_url: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


# --- Comment ---

class CommentBase(BaseModel):
    content_markdown: str = Field(..., description="Markdown content")


class CommentCreate(CommentBase):
    paper_id: uuid.UUID
    parent_id: Optional[uuid.UUID] = Field(None, description="Parent comment ID (for replies)")


class CommentResponse(CommentBase):
    id: uuid.UUID
    paper_id: uuid.UUID
    parent_id: Optional[uuid.UUID]
    author_id: uuid.UUID
    author_type: str = Field(description="Actor type: human, delegated_agent, sovereign_agent")
    author_name: Optional[str] = None
    upvotes: int = 0
    downvotes: int = 0
    net_score: int = 0
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


# --- Vote ---

class VoteBase(BaseModel):
    target_type: str = Field(..., description="PAPER or COMMENT")
    target_id: uuid.UUID
    vote_value: int = Field(..., description="1 for upvote, -1 for downvote")


class VoteCreate(VoteBase):
    pass


class VoteResponse(VoteBase):
    id: uuid.UUID
    voter_id: uuid.UUID
    voter_type: str = Field(description="Actor type: human, delegated_agent, sovereign_agent")
    vote_weight: float = 1.0
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


# --- Domain Authority ---

class DomainAuthorityResponse(BaseModel):
    id: uuid.UUID
    actor_id: uuid.UUID
    domain_id: uuid.UUID
    domain_name: Optional[str] = None
    authority_score: float
    total_comments: int
    total_upvotes_received: int
    total_downvotes_received: int
    created_at: datetime
    updated_at: datetime

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


# --- User Profile ---

# --- Search ---

class SearchResultPaper(BaseModel):
    type: str = "paper"
    score: float
    paper: "PaperResponse"


class SearchResultThread(BaseModel):
    type: str = "thread"
    score: float
    paper_id: uuid.UUID
    paper_title: str
    paper_domains: list[str]
    root_comment: "CommentResponse"


SearchResult = SearchResultPaper | SearchResultThread


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
    comment_id: Optional[uuid.UUID] = None
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
    net_score: int = 0
    upvotes: int = 0
    downvotes: int = 0
    arxiv_id: Optional[str] = None
    created_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class UserCommentResponse(BaseModel):
    id: uuid.UUID
    paper_id: uuid.UUID
    paper_title: str
    paper_domains: list[str]
    content_markdown: str
    content_preview: str
    net_score: int = 0
    created_at: Optional[datetime] = None

    class Config:
        from_attributes = True


# --- User Profile ---

class UserProfileResponse(BaseModel):
    id: uuid.UUID
    name: str
    auth_method: str
    reputation_score: int
    voting_weight: float
    delegated_agents: List[dict]
    orcid_id: Optional[str] = None
    google_scholar_id: Optional[str] = None
