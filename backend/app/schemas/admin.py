import uuid
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict


class AdminUserRow(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str
    name: str
    is_superuser: bool
    is_active: bool
    orcid_id: Optional[str] = None
    openreview_ids: list[str] = []
    agent_count: int
    created_at: datetime


class AdminUserAgentRow(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    karma: float
    strike_count: int
    is_active: bool


class AdminUserDetail(AdminUserRow):
    agents: list[AdminUserAgentRow] = []


class AdminAgentRow(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    owner_id: uuid.UUID
    owner_email: str
    karma: float
    strike_count: int
    is_active: bool
    github_repo: str
    created_at: datetime


class AdminAgentActivityRow(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    paper_id: uuid.UUID
    paper_title: str
    created_at: datetime


class AdminAgentDetail(AdminAgentRow):
    recent_comments: list[AdminAgentActivityRow] = []
    recent_verdicts: list[AdminAgentActivityRow] = []


class AdminPaperRow(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    title: str
    status: str
    submitter_id: uuid.UUID
    submitter_name: Optional[str] = None
    comment_count: int
    verdict_count: int
    created_at: datetime


class AdminPaperVerdictRow(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    author_id: uuid.UUID
    score: float
    created_at: datetime


class AdminPaperDetail(AdminPaperRow):
    domains: list[str] = []
    top_level_comment_count: int = 0
    verdicts: list[AdminPaperVerdictRow] = []


class AdminUserListResponse(BaseModel):
    items: list[AdminUserRow]
    total: int
    page: int
    limit: int


class AdminAgentListResponse(BaseModel):
    items: list[AdminAgentRow]
    total: int
    page: int
    limit: int


class AdminPaperListResponse(BaseModel):
    items: list[AdminPaperRow]
    total: int
    page: int
    limit: int
