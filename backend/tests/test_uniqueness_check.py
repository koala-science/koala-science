"""The `uniqueness` check: has this argument already been made about this paper?

Embedder and judge are stubbed throughout — these assert on which candidates
reach the judge and what the check does with the answer, not on model quality.
"""
import itertools
import math
import uuid
from datetime import datetime, timedelta

import pytest
from sqlalchemy import delete, select

from app.core import checks_uniqueness
from app.core.checks_uniqueness import (
    MAX_JUDGED_CANDIDATES,
    UNIQUENESS_THRESHOLD,
    uniqueness_check,
)
from app.core.gemini import CheckUnavailableError
from app.core.similarity_judge import DIFFERENT_ARGUMENT, DIFFERENT_SUBJECT, SAME_ARGUMENT
from app.models.identity import Agent, HumanAccount
from app.models.platform import (
    Argument,
    ArgumentCheck,
    ArgumentEmbedding,
    ArgumentPosition,
    ArgumentState,
    Paper,
)


@pytest.fixture(autouse=True)
async def _isolate(db_session):
    await db_session.execute(delete(ArgumentEmbedding))
    await db_session.execute(delete(ArgumentCheck))
    await db_session.execute(delete(Argument))
    await db_session.flush()


def _unit(*components: float) -> list[float]:
    """A vector on the unit sphere, padded out to the model's width."""
    vec = list(components) + [0.0] * (checks_uniqueness.EMBEDDING_DIMS - len(components))
    norm = math.sqrt(sum(v * v for v in vec))
    return [v / norm for v in vec]


ALIGNED = _unit(1.0, 0.0)
NEARLY_ALIGNED = _unit(0.95, 0.3122498999199199)   # cos with ALIGNED ~= 0.95
FAR = _unit(0.0, 1.0)                              # cos with ALIGNED == 0.0


class _Recorder:
    """Stub judge: hands out a scripted label per call and counts the calls."""

    def __init__(self, *labels: str):
        self.labels = list(labels)
        self.calls: list[tuple[str, str]] = []

    async def __call__(self, argument, candidate, *, paper_title, paper_abstract):
        self.calls.append((argument.claim, candidate.claim))
        return self.labels[len(self.calls) - 1] if self.labels else DIFFERENT_SUBJECT


async def _paper(db_session) -> tuple[Paper, Agent]:
    suffix = uuid.uuid4().hex[:8]
    owner = HumanAccount(name=f"owner_{suffix}", email=f"{suffix}@example.com")
    db_session.add(owner)
    await db_session.flush()

    agent = Agent(
        name=f"agent_{suffix}",
        owner_id=owner.id,
        api_key_hash=f"hash_{suffix}",
        api_key_lookup=f"lookup_{suffix}",
        github_repo="https://github.com/example/agent",
    )
    db_session.add(agent)
    await db_session.flush()

    paper = Paper(
        title="A paper", abstract="An abstract.", domains=["NLP"], submitter_id=agent.id
    )
    db_session.add(paper)
    await db_session.flush()
    return paper, agent


# Every row a test inserts shares one transaction, and Postgres' now() is the
# transaction timestamp — so created_at would be identical across them and
# "earlier" would come down to a random uuid. Tests state the order themselves.
_BASE_TIME = datetime(2026, 1, 1, 12, 0, 0)
_tick = itertools.count()


async def _argument(
    db_session, paper, agent, claim, *, vector=None, state=ArgumentState.PENDING
) -> Argument:
    argument = Argument(
        paper_id=paper.id,
        author_id=agent.id,
        claim=claim,
        position=ArgumentPosition.NEGATIVE,
        evidence="Table 2 omits it.",
        state=state,
        created_at=_BASE_TIME + timedelta(seconds=next(_tick)),
    )
    db_session.add(argument)
    await db_session.flush()
    if vector is not None:
        db_session.add(
            ArgumentEmbedding(
                argument_id=argument.id,
                model=checks_uniqueness.EMBEDDING_MODEL,
                vector=vector,
            )
        )
        await db_session.flush()
    return argument


def _stub_embedder(monkeypatch, vector, counter=None):
    async def _embed(text: str) -> list[float]:
        if counter is not None:
            counter.append(text)
        return vector

    monkeypatch.setattr(checks_uniqueness, "embed_claim", _embed)


async def test_first_argument_on_a_paper_passes_without_judging(db_session, monkeypatch):
    paper, agent = await _paper(db_session)
    argument = await _argument(db_session, paper, agent, "The baseline is missing.")
    _stub_embedder(monkeypatch, ALIGNED)
    judge = _Recorder()
    monkeypatch.setattr(checks_uniqueness, "judge_pair", judge)

    passed, detail = await uniqueness_check(db_session, argument)

    assert passed is True
    assert judge.calls == []
    assert "candidates=0" in detail


async def test_embedding_is_stored_normalized(db_session, monkeypatch):
    paper, agent = await _paper(db_session)
    argument = await _argument(db_session, paper, agent, "The baseline is missing.")
    _stub_embedder(monkeypatch, ALIGNED)
    monkeypatch.setattr(checks_uniqueness, "judge_pair", _Recorder())

    await uniqueness_check(db_session, argument)
    await db_session.flush()

    row = (
        await db_session.execute(
            select(ArgumentEmbedding).where(ArgumentEmbedding.argument_id == argument.id)
        )
    ).scalar_one()
    assert row.model == checks_uniqueness.EMBEDDING_MODEL
    assert len(row.vector) == checks_uniqueness.EMBEDDING_DIMS
    assert abs(sum(v * v for v in row.vector) - 1.0) < 1e-5


async def test_candidate_below_threshold_never_reaches_the_judge(db_session, monkeypatch):
    """The cosine gate decides what gets judged, not just what gets rejected."""
    paper, agent = await _paper(db_session)
    await _argument(db_session, paper, agent, "Prior, unrelated.", vector=FAR)
    argument = await _argument(db_session, paper, agent, "The baseline is missing.")
    _stub_embedder(monkeypatch, ALIGNED)
    judge = _Recorder(SAME_ARGUMENT)
    monkeypatch.setattr(checks_uniqueness, "judge_pair", judge)

    passed, detail = await uniqueness_check(db_session, argument)

    assert passed is True
    assert judge.calls == []


@pytest.mark.parametrize("label,expected_pass", [
    (SAME_ARGUMENT, False),
    (DIFFERENT_ARGUMENT, True),
    (DIFFERENT_SUBJECT, True),
    ("same subject, same argument, different evidence", False),
    ("same subject, same argument, same evidence", False),
])
async def test_verdict_follows_the_judge_label(db_session, monkeypatch, label, expected_pass):
    paper, agent = await _paper(db_session)
    await _argument(db_session, paper, agent, "Prior, similar.", vector=NEARLY_ALIGNED)
    argument = await _argument(db_session, paper, agent, "The baseline is missing.")
    _stub_embedder(monkeypatch, ALIGNED)
    monkeypatch.setattr(checks_uniqueness, "judge_pair", _Recorder(label))

    passed, _ = await uniqueness_check(db_session, argument)

    assert passed is expected_pass


async def test_failure_detail_names_the_duplicated_argument(db_session, monkeypatch):
    paper, agent = await _paper(db_session)
    prior = await _argument(db_session, paper, agent, "Prior, similar.", vector=NEARLY_ALIGNED)
    argument = await _argument(db_session, paper, agent, "The baseline is missing.")
    _stub_embedder(monkeypatch, ALIGNED)
    monkeypatch.setattr(checks_uniqueness, "judge_pair", _Recorder(SAME_ARGUMENT))

    passed, detail = await uniqueness_check(db_session, argument)

    assert passed is False
    assert str(prior.id) in detail
    assert SAME_ARGUMENT in detail
    assert "0.95" in detail


async def test_rejected_predecessor_is_not_a_candidate(db_session, monkeypatch):
    paper, agent = await _paper(db_session)
    await _argument(
        db_session, paper, agent, "Rejected twin.",
        vector=NEARLY_ALIGNED, state=ArgumentState.REJECTED,
    )
    argument = await _argument(db_session, paper, agent, "The baseline is missing.")
    _stub_embedder(monkeypatch, ALIGNED)
    judge = _Recorder(SAME_ARGUMENT)
    monkeypatch.setattr(checks_uniqueness, "judge_pair", judge)

    passed, _ = await uniqueness_check(db_session, argument)

    assert passed is True
    assert judge.calls == []


async def test_later_argument_is_not_a_candidate(db_session, monkeypatch):
    """Only earlier arguments count, so the first proposer of a claim wins."""
    paper, agent = await _paper(db_session)
    argument = await _argument(db_session, paper, agent, "The baseline is missing.")
    await _argument(db_session, paper, agent, "Later twin.", vector=NEARLY_ALIGNED)
    _stub_embedder(monkeypatch, ALIGNED)
    judge = _Recorder(SAME_ARGUMENT)
    monkeypatch.setattr(checks_uniqueness, "judge_pair", judge)

    passed, _ = await uniqueness_check(db_session, argument)

    assert passed is True
    assert judge.calls == []


async def test_other_papers_are_not_candidates(db_session, monkeypatch):
    paper, agent = await _paper(db_session)
    other_paper, other_agent = await _paper(db_session)
    await _argument(db_session, other_paper, other_agent, "Same claim elsewhere.",
                    vector=NEARLY_ALIGNED)
    argument = await _argument(db_session, paper, agent, "The baseline is missing.")
    _stub_embedder(monkeypatch, ALIGNED)
    judge = _Recorder(SAME_ARGUMENT)
    monkeypatch.setattr(checks_uniqueness, "judge_pair", judge)

    passed, _ = await uniqueness_check(db_session, argument)

    assert passed is True
    assert judge.calls == []


async def test_predecessor_without_an_embedding_is_invisible(db_session, monkeypatch):
    """A predecessor still in moderation or validity has no vector yet, which is
    what keeps it from causing a rejection it might never have earned."""
    paper, agent = await _paper(db_session)
    await _argument(db_session, paper, agent, "Unembedded twin.", vector=None)
    argument = await _argument(db_session, paper, agent, "The baseline is missing.")
    _stub_embedder(monkeypatch, ALIGNED)
    judge = _Recorder(SAME_ARGUMENT)
    monkeypatch.setattr(checks_uniqueness, "judge_pair", judge)

    passed, _ = await uniqueness_check(db_session, argument)

    assert passed is True
    assert judge.calls == []


async def test_stops_at_the_first_duplicate(db_session, monkeypatch):
    paper, agent = await _paper(db_session)
    for i in range(3):
        await _argument(db_session, paper, agent, f"Prior {i}.", vector=NEARLY_ALIGNED)
    argument = await _argument(db_session, paper, agent, "The baseline is missing.")
    _stub_embedder(monkeypatch, ALIGNED)
    judge = _Recorder(SAME_ARGUMENT, DIFFERENT_SUBJECT, DIFFERENT_SUBJECT)
    monkeypatch.setattr(checks_uniqueness, "judge_pair", judge)

    passed, _ = await uniqueness_check(db_session, argument)

    assert passed is False
    assert len(judge.calls) == 1


async def test_judges_every_candidate_when_none_match(db_session, monkeypatch):
    paper, agent = await _paper(db_session)
    for i in range(3):
        await _argument(db_session, paper, agent, f"Prior {i}.", vector=NEARLY_ALIGNED)
    argument = await _argument(db_session, paper, agent, "The baseline is missing.")
    _stub_embedder(monkeypatch, ALIGNED)
    judge = _Recorder(*[DIFFERENT_ARGUMENT] * 3)
    monkeypatch.setattr(checks_uniqueness, "judge_pair", judge)

    passed, detail = await uniqueness_check(db_session, argument)

    assert passed is True
    assert len(judge.calls) == 3
    assert "candidates=3" in detail


async def test_cap_bounds_the_judge_and_is_reported(db_session, monkeypatch):
    """A silent truncation would report a clean 'unique' for a check that only
    looked at part of the field."""
    paper, agent = await _paper(db_session)
    for i in range(MAX_JUDGED_CANDIDATES + 3):
        await _argument(db_session, paper, agent, f"Prior {i}.", vector=NEARLY_ALIGNED)
    argument = await _argument(db_session, paper, agent, "The baseline is missing.")
    _stub_embedder(monkeypatch, ALIGNED)
    judge = _Recorder(*[DIFFERENT_SUBJECT] * (MAX_JUDGED_CANDIDATES + 3))
    monkeypatch.setattr(checks_uniqueness, "judge_pair", judge)

    passed, detail = await uniqueness_check(db_session, argument)

    assert passed is True
    assert len(judge.calls) == MAX_JUDGED_CANDIDATES
    assert "truncated" in detail


async def test_embedding_outage_raises_rather_than_passing(db_session, monkeypatch):
    """An embedder that returned nothing would look exactly like 'no match'."""
    paper, agent = await _paper(db_session)
    argument = await _argument(db_session, paper, agent, "The baseline is missing.")

    async def _down(text: str) -> list[float]:
        raise CheckUnavailableError("embedding endpoint down")

    monkeypatch.setattr(checks_uniqueness, "embed_claim", _down)
    monkeypatch.setattr(checks_uniqueness, "judge_pair", _Recorder())

    with pytest.raises(CheckUnavailableError):
        await uniqueness_check(db_session, argument)


async def test_judge_outage_raises_rather_than_passing(db_session, monkeypatch):
    paper, agent = await _paper(db_session)
    await _argument(db_session, paper, agent, "Prior, similar.", vector=NEARLY_ALIGNED)
    argument = await _argument(db_session, paper, agent, "The baseline is missing.")
    _stub_embedder(monkeypatch, ALIGNED)

    async def _down(argument, candidate, *, paper_title, paper_abstract):
        raise CheckUnavailableError("judge down")

    monkeypatch.setattr(checks_uniqueness, "judge_pair", _down)

    with pytest.raises(CheckUnavailableError):
        await uniqueness_check(db_session, argument)


async def test_predecessor_vectors_are_reused_not_recomputed(db_session, monkeypatch):
    paper, agent = await _paper(db_session)
    await _argument(db_session, paper, agent, "Prior, similar.", vector=NEARLY_ALIGNED)
    argument = await _argument(db_session, paper, agent, "The baseline is missing.")
    embedded: list[str] = []
    _stub_embedder(monkeypatch, ALIGNED, counter=embedded)
    monkeypatch.setattr(checks_uniqueness, "judge_pair", _Recorder(DIFFERENT_SUBJECT))

    await uniqueness_check(db_session, argument)

    assert embedded == [argument.claim]


async def test_only_the_claim_is_embedded(db_session, monkeypatch):
    paper, agent = await _paper(db_session)
    argument = await _argument(db_session, paper, agent, "The baseline is missing.")
    embedded: list[str] = []
    _stub_embedder(monkeypatch, ALIGNED, counter=embedded)
    monkeypatch.setattr(checks_uniqueness, "judge_pair", _Recorder())

    await uniqueness_check(db_session, argument)

    assert embedded == ["The baseline is missing."]
    assert argument.evidence not in embedded


async def test_rechecking_reuses_the_stored_vector(db_session, monkeypatch):
    """Bumping the check version runs uniqueness again on an argument that
    already has a vector. Colliding with the unique constraint here would raise
    out of the worker's failure handler and crash-loop the process."""
    paper, agent = await _paper(db_session)
    argument = await _argument(db_session, paper, agent, "The baseline is missing.")
    _stub_embedder(monkeypatch, ALIGNED)
    monkeypatch.setattr(checks_uniqueness, "judge_pair", _Recorder())

    assert (await uniqueness_check(db_session, argument))[0] is True
    assert (await uniqueness_check(db_session, argument))[0] is True

    rows = (
        await db_session.execute(
            select(ArgumentEmbedding).where(ArgumentEmbedding.argument_id == argument.id)
        )
    ).scalars().all()
    assert len(rows) == 1


async def test_a_rejected_argument_stores_no_vector(db_session, monkeypatch):
    paper, agent = await _paper(db_session)
    await _argument(db_session, paper, agent, "Prior, similar.", vector=NEARLY_ALIGNED)
    argument = await _argument(db_session, paper, agent, "The baseline is missing.")
    _stub_embedder(monkeypatch, ALIGNED)
    monkeypatch.setattr(checks_uniqueness, "judge_pair", _Recorder(SAME_ARGUMENT))

    passed, _ = await uniqueness_check(db_session, argument)

    assert passed is False
    stored = (
        await db_session.execute(
            select(ArgumentEmbedding.id).where(
                ArgumentEmbedding.argument_id == argument.id
            )
        )
    ).scalar_one_or_none()
    assert stored is None


def test_threshold_matches_the_calibration():
    """0.8 is carried over from analysis/scripts/coverage_pipeline.py's
    --judge-threshold. Changing it invalidates the calibration."""
    assert UNIQUENESS_THRESHOLD == 0.8
