import uuid

import pytest
from pydantic import ValidationError

from app.schemas.platform import ArgumentCreate, AuthorResponseCreate, CheckFlagCreate


PAPER_ID = str(uuid.uuid4())


@pytest.mark.parametrize("field", ["claim", "evidence"])
def test_argument_rejects_field_over_cap(field):
    payload = {
        "paper_id": PAPER_ID,
        "claim": "A claim.",
        "position": "negative",
        "evidence": "Some evidence.",
    }
    payload[field] = "x" * 10_001
    with pytest.raises(ValidationError):
        ArgumentCreate(**payload)


@pytest.mark.parametrize("field", ["claim", "evidence"])
def test_argument_accepts_field_at_cap(field):
    payload = {
        "paper_id": PAPER_ID,
        "claim": "A claim.",
        "position": "negative",
        "evidence": "Some evidence.",
    }
    payload[field] = "x" * 10_000
    assert len(getattr(ArgumentCreate(**payload), field)) == 10_000


def test_check_flag_reason_rejected_over_cap():
    with pytest.raises(ValidationError):
        CheckFlagCreate(check_id=str(uuid.uuid4()), reason="x" * 2_001)


def test_check_flag_reason_accepted_at_cap():
    flag = CheckFlagCreate(check_id=str(uuid.uuid4()), reason="x" * 2_000)
    assert len(flag.reason) == 2_000


def test_author_response_rejected_over_cap():
    with pytest.raises(ValidationError):
        AuthorResponseCreate(body="x" * 1_001)


def test_author_response_accepted_at_cap():
    assert len(AuthorResponseCreate(body="x" * 1_000).body) == 1_000
