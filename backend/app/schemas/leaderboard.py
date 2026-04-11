"""
Pydantic schemas for leaderboard API endpoints.
"""
import uuid
from typing import Optional, List
from pydantic import BaseModel, Field
from datetime import datetime


# --- Agent Leaderboard ---

class AgentLeaderboardEntry(BaseModel):
    """A single row in the agent leaderboard."""
    rank: int
    agent_id: uuid.UUID
    agent_name: str
    agent_type: str = Field(description="Actor type: delegated_agent or sovereign_agent")
    owner_name: Optional[str] = Field(None, description="Name of the human owner (for delegated agents)")
    score: float
    num_papers_evaluated: int

    class Config:
        from_attributes = True


class AgentLeaderboardResponse(BaseModel):
    """Response for the agent leaderboard endpoint."""
    metric: str
    entries: List[AgentLeaderboardEntry]
    total: int


# --- Paper Leaderboard ---

class PaperLeaderboardEntry(BaseModel):
    """A single row in the paper leaderboard."""
    rank: int
    paper_id: uuid.UUID
    title: str
    domains: list[str]
    score: float
    arxiv_id: Optional[str] = None
    submitter_name: Optional[str] = None

    class Config:
        from_attributes = True


class PaperLeaderboardResponse(BaseModel):
    """Response for the paper leaderboard endpoint."""
    entries: List[PaperLeaderboardEntry]
    total: int
