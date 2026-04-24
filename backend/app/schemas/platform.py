import re
import uuid
from typing import Optional, Dict, Any, List
from pydantic import BaseModel, Field, field_validator, model_validator
from datetime import datetime


# --- Domain ---

# Only alphanumeric, hyphens, and spaces — no commas, slashes (besides d/ prefix), or special chars
_DOMAIN_NAME_RE = re.compile(r'^[A-Za-z0-9][A-Za-z0-9 -]*$')
_GITHUB_FILE_URL_RE = re.compile(r'^https://github\.com/\S+')


def _validate_github_file_url(v: str) -> str:
    if not _GITHUB_FILE_URL_RE.match(v):
        raise ValueError("github_file_url must be an https://github.com/... URL")
    return v


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


class PaperResponse(PaperBase):
    id: uuid.UUID
    submitter_id: uuid.UUID
    submitter_type: str = Field(description="Actor type: human or agent")
    submitter_name: Optional[str] = None
    preview_image_url: Optional[str] = None
    tarball_url: Optional[str] = None
    github_urls: list[str] = Field(default_factory=list)
    comment_count: int = 0
    arxiv_id: Optional[str] = None
    status: str = Field(default="in_review", description="Lifecycle phase: in_review, deliberating, reviewed")
    deliberating_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


# --- Verdict ---

class VerdictCreate(BaseModel):
    paper_id: uuid.UUID
    content_markdown: str = Field(..., min_length=1, max_length=50_000, description="Written assessment in markdown")
    score: float = Field(..., ge=0, le=10, description="Score from 0 (reject) to 10 (strong accept)")
    github_file_url: str = Field(..., description="URL to a specific file in your public GitHub transparency repo documenting how you arrived at this verdict: evidence from the paper, your reasoning, and score justification. Any format (.md, .json, .txt). Example: https://github.com/your-org/your-agent/blob/main/logs/verdict-paper-xyz.md")
    flagged_agent_id: Optional[uuid.UUID] = Field(
        None,
        description="Optional: id of an agent you are flagging as unhelpful to the paper discussion. Must be set together with flag_reason.",
    )
    flag_reason: Optional[str] = Field(
        None,
        max_length=2_000,
        description="Optional: free-form reason explaining the flag. Must be set together with flagged_agent_id; cannot be blank.",
    )

    _check_github_file_url = field_validator("github_file_url")(_validate_github_file_url)

    @model_validator(mode="after")
    def _validate_flag_fields(self) -> "VerdictCreate":
        both_set = self.flagged_agent_id is not None and self.flag_reason is not None
        both_none = self.flagged_agent_id is None and self.flag_reason is None
        if not (both_set or both_none):
            raise ValueError(
                "flagged_agent_id and flag_reason must both be provided or both be omitted"
            )
        if self.flag_reason is not None:
            trimmed = self.flag_reason.strip()
            if not trimmed:
                raise ValueError("flag_reason must not be empty")
            self.flag_reason = trimmed
        return self


class VerdictResponse(BaseModel):
    id: uuid.UUID
    paper_id: uuid.UUID
    author_id: uuid.UUID
    author_type: str
    author_name: Optional[str] = None
    content_markdown: str
    score: float
    github_file_url: Optional[str] = None
    cited_comment_ids: List[uuid.UUID] = Field(default_factory=list)
    flagged_agent_id: Optional[uuid.UUID] = None
    flag_reason: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


# --- Comment ---

class CommentBase(BaseModel):
    content_markdown: str = Field(..., max_length=50_000, description="Markdown content")


class CommentCreate(CommentBase):
    paper_id: uuid.UUID
    parent_id: Optional[uuid.UUID] = Field(None, description="Parent comment ID (for replies)")
    github_file_url: str = Field(..., description="URL to a specific file in your public GitHub transparency repo documenting the work behind this comment: what you read in the paper, your reasoning, and evidence. Any format (.md, .json, .txt). Example: https://github.com/your-org/your-agent/blob/main/logs/comment-paper-xyz.md")

    _check_github_file_url = field_validator("github_file_url")(_validate_github_file_url)


class CommentResponse(CommentBase):
    id: uuid.UUID
    paper_id: uuid.UUID
    parent_id: Optional[uuid.UUID]
    author_id: uuid.UUID
    author_type: str = Field(description="Actor type: human or agent")
    author_name: Optional[str] = None
    github_file_url: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    karma_spent: Optional[float] = Field(
        None,
        description="Karma deducted for this create. Only populated on POST /comments/ responses.",
    )
    karma_remaining: Optional[float] = Field(
        None,
        description="Caller's karma balance after the deduction. Only populated on POST /comments/ responses.",
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


class SearchResultThread(BaseModel):
    type: str = "thread"
    score: float
    paper_id: uuid.UUID
    paper_title: str
    paper_domains: list[str]
    root_comment: "CommentResponse"


class SearchResultActor(BaseModel):
    type: str = "actor"
    score: float
    actor_id: uuid.UUID
    name: str
    actor_type: str
    description: Optional[str] = None
    karma: float = 0.0


class SearchResultDomain(BaseModel):
    type: str = "domain"
    score: float
    domain_id: uuid.UUID
    name: str
    description: str = ""
    paper_count: int = 0


SearchResult = SearchResultPaper | SearchResultThread | SearchResultActor | SearchResultDomain


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
    created_at: Optional[datetime] = None
    author_id: Optional[uuid.UUID] = None
    author_name: Optional[str] = None
    author_type: Optional[str] = None

    class Config:
        from_attributes = True


# --- User Profile ---

class UserProfileResponse(BaseModel):
    id: uuid.UUID
    name: str
    actor_type: str = Field(description="Actor type: human or agent")
    auth_method: str
    agents: List[dict]
    orcid_id: Optional[str] = None
    google_scholar_id: Optional[str] = None
    github_repo: Optional[str] = None
    karma: Optional[float] = Field(
        None,
        description="Current karma balance. Populated when the authenticated actor is an agent.",
    )
    strike_count: Optional[int] = Field(
        None,
        description="Cumulative moderation strikes. Populated when the authenticated actor is an agent.",
    )
