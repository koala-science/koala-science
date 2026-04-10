import uuid
from typing import Optional, Dict, Any, List
from pydantic import BaseModel, Field
from datetime import datetime


# --- Domain ---

class DomainBase(BaseModel):
    name: str = Field(..., description="Name of the domain")
    description: str = Field(..., description="Description of the domain")


class DomainCreate(DomainBase):
    pass


class DomainResponse(DomainBase):
    id: uuid.UUID
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

class PaperBase(BaseModel):
    title: str = Field(..., description="Title of the paper")
    abstract: str = Field(..., description="Abstract of the paper")
    domain: str = Field(..., description="The domain or category (e.g., d/LLM-Alignment)")
    pdf_url: Optional[str] = Field(None, description="URL to the PDF document")
    github_repo_url: Optional[str] = Field(None, description="URL to the GitHub repository")


class PaperCreate(PaperBase):
    pass


class PaperIngest(BaseModel):
    arxiv_url: str = Field(..., description="arXiv URL or ID to ingest")
    domain: Optional[str] = Field(None, description="Override domain assignment")


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
    total_reviews: int
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
    paper_domain: str
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


# --- User Activity ---

class UserPaperResponse(BaseModel):
    id: uuid.UUID
    title: str
    abstract: str
    domain: str
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
    paper_domain: str
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
