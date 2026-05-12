"""Annotation models for the human-rating pipeline.

Snapshot-driven, **paper-centric** design (v2): every batch builds a
shared *pool* of papers via a greedy algorithm — each eligible agent
ends up with K papers from the pool in their per-agent slate, and the
same paper can be reused across multiple agents who commented on it.
Annotators are then assigned to *papers* (not agents), so the cost of
deeply reading a paper amortizes across every (agent, paper) tuple
hung off that pool entry.

Ratings remain at two levels:

- PAPER: one rating per (annotator, agent, paper).
- COMMENT: one rating per (annotator, agent, paper, comment).

AGENT-level questions are dropped in v2 — agent-level conclusions are
derived from per-paper annotations.

Two annotators per paper gives us inter-rater agreement.
"""
import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base_class import Base


class AnnotationLevel(str, enum.Enum):
    AGENT = "AGENT"
    PAPER = "PAPER"
    COMMENT = "COMMENT"
    FACT = "FACT"


class AnnotationResponseType(str, enum.Enum):
    LIKERT_5 = "LIKERT_5"
    LIKERT_7 = "LIKERT_7"
    SINGLE_CHOICE = "SINGLE_CHOICE"
    MULTI_CHOICE = "MULTI_CHOICE"
    FREE_TEXT = "FREE_TEXT"
    BOOLEAN = "BOOLEAN"


class AnnotationBatch(Base):
    __tablename__ = "annotation_batch"

    name: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    random_seed: Mapped[int] = mapped_column(BigInteger, nullable=False)
    min_papers_threshold: Mapped[int] = mapped_column(Integer, nullable=False)
    sample_size: Mapped[int] = mapped_column(Integer, nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)


class AnnotationBatchAgent(Base):
    __tablename__ = "annotation_batch_agent"

    batch_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("annotation_batch.id", ondelete="CASCADE"), nullable=False
    )
    agent_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("agent.id", ondelete="RESTRICT"), nullable=False
    )
    score_histogram_json: Mapped[list] = mapped_column(JSONB, nullable=False)
    total_verdicts: Mapped[int] = mapped_column(Integer, nullable=False)

    __table_args__ = (
        UniqueConstraint("batch_id", "agent_id", name="uq_batch_agent"),
    )


class AnnotationBatchPaper(Base):
    """One row per paper in the batch's shared pool."""

    __tablename__ = "annotation_batch_paper"

    batch_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("annotation_batch.id", ondelete="CASCADE"), nullable=False
    )
    paper_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("paper.id", ondelete="RESTRICT"), nullable=False
    )
    pool_index: Mapped[int] = mapped_column(Integer, nullable=False)

    __table_args__ = (
        UniqueConstraint("batch_id", "paper_id", name="uq_batch_paper_pool"),
    )


class AnnotationBatchAgentPaper(Base):
    """Joins a ``batch_agent`` to one of its K pool papers."""

    __tablename__ = "annotation_batch_agent_paper"

    batch_agent_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("annotation_batch_agent.id", ondelete="CASCADE"),
        nullable=False,
    )
    batch_paper_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("annotation_batch_paper.id", ondelete="CASCADE"),
        nullable=False,
    )
    sample_index: Mapped[int] = mapped_column(Integer, nullable=False)

    __table_args__ = (
        UniqueConstraint(
            "batch_agent_id",
            "batch_paper_id",
            name="uq_batch_agent_paper_link",
        ),
        Index(
            "ix_annotation_batch_agent_paper_paper",
            "batch_paper_id",
        ),
    )


class AnnotationBatchFact(Base):
    """One row per fact sampled into a (batch, agent, paper) tuple's FACT slate."""

    __tablename__ = "annotation_batch_fact"

    batch_agent_paper_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey(
            "annotation_batch_agent_paper.id", ondelete="CASCADE"
        ),
        nullable=False,
    )
    comment_fact_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("comment_fact.id", ondelete="RESTRICT"), nullable=False
    )
    sample_index: Mapped[int] = mapped_column(Integer, nullable=False)

    __table_args__ = (
        UniqueConstraint(
            "batch_agent_paper_id",
            "comment_fact_id",
            name="uq_batch_fact_link",
        ),
        Index(
            "ix_annotation_batch_fact_bap",
            "batch_agent_paper_id",
        ),
    )


class AnnotationAssignment(Base):
    __tablename__ = "annotation_assignment"

    batch_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("annotation_batch.id", ondelete="CASCADE"), nullable=False
    )
    annotator_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("human_account.id", ondelete="RESTRICT"), nullable=False
    )
    batch_paper_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("annotation_batch_paper.id", ondelete="CASCADE"),
        nullable=False,
    )

    __table_args__ = (
        UniqueConstraint(
            "batch_paper_id", "annotator_id", name="uq_assignment_paper"
        ),
    )


class AnnotationQuestion(Base):
    __tablename__ = "annotation_question"

    level: Mapped[AnnotationLevel] = mapped_column(
        Enum(
            AnnotationLevel,
            name="annotationlevel",
            values_callable=lambda e: [m.value for m in e],
        ),
        nullable=False,
    )
    prompt: Mapped[str] = mapped_column(Text, nullable=False)
    response_type: Mapped[AnnotationResponseType] = mapped_column(
        Enum(
            AnnotationResponseType,
            name="annotationresponsetype",
            values_callable=lambda e: [m.value for m in e],
        ),
        nullable=False,
    )
    choices_json: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    order_index: Mapped[int] = mapped_column(Integer, nullable=False)
    retired_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class AnnotationResponse(Base):
    __tablename__ = "annotation_response"

    batch_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("annotation_batch.id", ondelete="CASCADE"), nullable=False
    )
    annotator_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("human_account.id", ondelete="RESTRICT"), nullable=False
    )
    question_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("annotation_question.id", ondelete="RESTRICT"), nullable=False
    )
    agent_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("agent.id", ondelete="RESTRICT"), nullable=False
    )
    paper_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("paper.id", ondelete="RESTRICT"), nullable=True
    )
    comment_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("comment.id", ondelete="RESTRICT"), nullable=True
    )
    fact_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("comment_fact.id", ondelete="CASCADE"), nullable=True
    )
    response_value_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    __table_args__ = (
        Index(
            "uq_response_agent",
            "batch_id",
            "annotator_id",
            "question_id",
            "agent_id",
            unique=True,
            postgresql_where=(
                "paper_id IS NULL AND comment_id IS NULL AND fact_id IS NULL"
            ),
        ),
        Index(
            "uq_response_paper",
            "batch_id",
            "annotator_id",
            "question_id",
            "agent_id",
            "paper_id",
            unique=True,
            postgresql_where=(
                "paper_id IS NOT NULL AND comment_id IS NULL "
                "AND fact_id IS NULL"
            ),
        ),
        Index(
            "uq_response_comment",
            "batch_id",
            "annotator_id",
            "question_id",
            "agent_id",
            "paper_id",
            "comment_id",
            unique=True,
            postgresql_where="comment_id IS NOT NULL AND fact_id IS NULL",
        ),
        Index(
            "uq_response_fact",
            "batch_id",
            "annotator_id",
            "question_id",
            "fact_id",
            unique=True,
            postgresql_where="fact_id IS NOT NULL",
        ),
        CheckConstraint(
            "(fact_id IS NULL AND ("
            "    (paper_id IS NULL AND comment_id IS NULL) "
            " OR (paper_id IS NOT NULL AND comment_id IS NULL) "
            " OR (paper_id IS NOT NULL AND comment_id IS NOT NULL)"
            ")) OR ("
            "  fact_id IS NOT NULL "
            "  AND agent_id IS NOT NULL "
            "  AND paper_id IS NOT NULL "
            "  AND comment_id IS NOT NULL"
            ")",
            name="annotation_response_level_shape",
        ),
    )


class AnnotationPageState(Base):
    __tablename__ = "annotation_page_state"

    batch_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("annotation_batch.id", ondelete="CASCADE"), nullable=False
    )
    annotator_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("human_account.id", ondelete="RESTRICT"), nullable=False
    )
    agent_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("agent.id", ondelete="RESTRICT"), nullable=False
    )
    paper_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("paper.id", ondelete="RESTRICT"), nullable=True
    )
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    __table_args__ = (
        UniqueConstraint(
            "annotator_id",
            "batch_id",
            "agent_id",
            "paper_id",
            name="uq_page_state",
        ),
    )


class CommentFact(Base):
    """An atomic factual claim extracted from a focal-agent comment.

    Populated offline by ``scripts/extract_facts.py``. See
    ``.claude/specs/fact-extraction.md`` for design notes. Extraction
    only — verification and significance scoring are out of scope.
    """

    __tablename__ = "comment_fact"

    comment_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("comment.id", ondelete="CASCADE"), nullable=False
    )
    fact_text: Mapped[str] = mapped_column(Text, nullable=False)
    fact_index: Mapped[int] = mapped_column(Integer, nullable=False)
    extractor_model: Mapped[str] = mapped_column(String(64), nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(32), nullable=False)
    extracted_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )

    __table_args__ = (
        Index("ix_comment_fact_comment_id", "comment_id"),
        UniqueConstraint(
            "comment_id",
            "prompt_version",
            "extractor_model",
            "fact_index",
            name="uq_comment_fact_comment_prompt_model_index",
        ),
    )


class CommentFactExtractionRun(Base):
    """Per-comment extraction attempt — including zero-fact and error runs.

    Each (comment, prompt_version, extractor_model) row is unique, so
    re-running the same extraction is an idempotency point. Stores the
    raw LLM response to allow audits and re-parses without re-calling
    the API.
    """

    __tablename__ = "comment_fact_extraction_run"

    comment_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("comment.id", ondelete="CASCADE"), nullable=False
    )
    extractor_model: Mapped[str] = mapped_column(String(64), nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    fact_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0", default=0
    )
    raw_response: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    input_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    output_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    extracted_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )

    __table_args__ = (
        UniqueConstraint(
            "comment_id",
            "prompt_version",
            "extractor_model",
            name="uq_comment_fact_extraction_run",
        ),
    )
