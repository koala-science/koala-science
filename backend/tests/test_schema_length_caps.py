import uuid

import pytest
from pydantic import ValidationError

from app.schemas.platform import CommentCreate, VerdictCreate


PAPER_ID = str(uuid.uuid4())
VALID_URL = "https://github.com/example/agent/blob/main/logs/x.md"
VERDICT_CITATIONS = " ".join(f"[[comment:{uuid.uuid4()}]]" for _ in range(5))


def test_comment_rejects_content_over_cap():
    with pytest.raises(ValidationError):
        CommentCreate(
            paper_id=PAPER_ID,
            content_markdown="a" * 50_001,
            github_file_url=VALID_URL,
        )


def test_comment_accepts_content_at_cap():
    body = "a" * 50_000
    obj = CommentCreate(
        paper_id=PAPER_ID,
        content_markdown=body,
        github_file_url=VALID_URL,
    )
    assert len(obj.content_markdown) == 50_000


def test_verdict_rejects_content_over_cap():
    with pytest.raises(ValidationError):
        VerdictCreate(
            paper_id=PAPER_ID,
            content_markdown="a" * 50_001,
            score=7.0,
            github_file_url=VALID_URL,
        )


def test_verdict_rejects_flag_reason_over_cap():
    with pytest.raises(ValidationError):
        VerdictCreate(
            paper_id=PAPER_ID,
            content_markdown=f"Substantive verdict body. {VERDICT_CITATIONS}",
            score=7.0,
            github_file_url=VALID_URL,
            flagged_agent_id=uuid.uuid4(),
            flag_reason="a" * 2_001,
        )
