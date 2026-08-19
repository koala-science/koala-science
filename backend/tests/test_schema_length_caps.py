import uuid

import pytest
from pydantic import ValidationError

from app.schemas.platform import ArgumentCreate


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
