"""The `uniqueness` check: has this argument already been made about this paper?

Ported from the coverage analysis in ``analysis/scripts/coverage_pipeline.py``,
which measures how many *distinct* arguments a reviewing method surfaces. The
method is two-stage:

  * embed the claim and take cosine against every earlier argument on the paper,
    which is cheap and settles the overwhelming majority of pairs;
  * send only the pairs above the threshold to an LLM judge, which decides
    whether they are actually the same argument.

Both numbers here — the 0.8 threshold and the label-to-duplicate mapping — are
carried over from that pipeline unchanged. Changing either invalidates the
calibration behind them.

Unlike the other two checks this one depends on the rest of the paper, which is
why it runs last: an argument that is spam or malformed is never compared against
anything, and never becomes something a later argument can collide with.
"""
import logging
import math

from google import genai
from google.genai import errors as genai_errors, types as genai_types
from sqlalchemy import func, select, tuple_
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.gemini import CheckUnavailableError, judge
from app.core.similarity_judge import (
    SYSTEM_PROMPT,
    USER_PROMPT_TEMPLATE,
    is_duplicate,
    match_label,
)
from app.models.platform import Argument, ArgumentEmbedding, ArgumentState

logger = logging.getLogger(__name__)

EMBEDDING_MODEL = "gemini-embedding-001"
EMBEDDING_DIMS = 3072

# Carried over from coverage_pipeline.py's --judge-threshold. Pairs below this
# are distinct without being judged; pairs above it are decided by the judge.
UNIQUENESS_THRESHOLD = 0.8

# Above the threshold a paper rarely has more than a handful of candidates. The
# cap bounds worst-case cost and lock time; when it truncates, the argument
# passes on partial evidence and ``detail`` records that it did.
MAX_JUDGED_CANDIDATES = 20

EMBEDDING_TIMEOUT_MS = 30_000

ABSTRACT_CHARS = 1800


async def embed_claim(text: str) -> list[float]:
    """The claim as an L2-normalized vector.

    Deliberately not ``app.core.embeddings.generate_embedding``: that one pins
    the output to 768 dimensions, and returns ``None`` on failure — which this
    check would read as "nothing to compare against" and pass every argument.
    """
    if not settings.GEMINI_API_KEY:
        raise CheckUnavailableError("GEMINI_API_KEY is not configured")

    client = genai.Client(
        api_key=settings.GEMINI_API_KEY,
        http_options=genai_types.HttpOptions(timeout=EMBEDDING_TIMEOUT_MS),
    )
    try:
        result = await client.aio.models.embed_content(
            model=EMBEDDING_MODEL,
            contents=text,
            config={"output_dimensionality": EMBEDDING_DIMS},
        )
    except genai_errors.APIError as exc:
        raise CheckUnavailableError(f"embedding request failed: {exc}") from exc

    vector = result.embeddings[0].values
    norm = math.sqrt(sum(v * v for v in vector))
    if norm == 0.0:
        raise CheckUnavailableError("embedding is the zero vector")
    return [v / norm for v in vector]


async def judge_pair(
    argument: Argument,
    candidate: Argument,
    *,
    paper_title: str,
    paper_abstract: str,
) -> str:
    """The judge's label for one pair. Raises if it did not produce one."""
    user_text = USER_PROMPT_TEMPLATE.format(
        paper_text=f"Title: {paper_title}\n\nAbstract: {paper_abstract[:ABSTRACT_CHARS]}",
        reviewer_a="A",
        reviewer_b="B",
        item_a=f"{argument.claim}\n\nEvidence: {argument.evidence}",
        item_b=f"{candidate.claim}\n\nEvidence: {candidate.evidence}",
    )
    response = await judge(SYSTEM_PROMPT, user_text)
    label = match_label(response)
    if label is None:
        raise CheckUnavailableError("judge returned no <answer> tag")
    return label


async def _candidates(
    db: AsyncSession, argument: Argument, vector: list[float]
) -> list[tuple[Argument, float]]:
    """Earlier arguments on this paper that survived, ordered most similar first.

    A predecessor is only here if it has been embedded, which happens when its
    own uniqueness check runs — so anything still in moderation or validity is
    invisible. That is the point: those are the predecessors that might yet be
    rejected, and colliding with one would cost this argument its point for a
    claim that never made it onto the paper.

    Ordering is by ``(created_at, id)`` rather than ``created_at`` alone: rows
    inserted in one transaction share a timestamp, and without the tiebreak
    which of them counts as earlier would depend on nothing at all.
    """
    rows = (
        await db.execute(
            select(Argument, ArgumentEmbedding.vector)
            .join(ArgumentEmbedding, ArgumentEmbedding.argument_id == Argument.id)
            .where(
                ArgumentEmbedding.model == EMBEDDING_MODEL,
                Argument.paper_id == argument.paper_id,
                Argument.state != ArgumentState.REJECTED,
                tuple_(Argument.created_at, Argument.id)
                < tuple_(argument.created_at, argument.id),
            )
        )
    ).all()

    scored = [
        (other, sum(x * y for x, y in zip(vector, other_vector, strict=True)))
        for other, other_vector in rows
    ]
    scored = [pair for pair in scored if pair[1] >= UNIQUENESS_THRESHOLD]
    scored.sort(key=lambda pair: pair[1], reverse=True)
    return scored


async def uniqueness_check(db: AsyncSession, argument: Argument) -> tuple[bool, str]:
    """The check-runner entry point.

    Raises on an upstream outage so the runner leaves the row pending — an
    outage must never reject an argument, nor cost its author a point.
    """
    # Serializes workers on one paper. Two arguments checked concurrently would
    # each be invisible to the other — neither vector is committed yet — and both
    # would pass, which is exactly the collision this check exists to catch.
    await db.execute(select(func.pg_advisory_xact_lock(func.hashtext(str(argument.paper_id)))))

    vector = await embed_claim(argument.claim)
    candidates = await _candidates(db, argument, vector)
    judged = candidates[:MAX_JUDGED_CANDIDATES]

    for candidate, similarity in judged:
        label = await judge_pair(
            argument,
            candidate,
            paper_title=argument.paper.title,
            paper_abstract=argument.paper.abstract,
        )
        logger.info(
            "uniqueness argument=%s vs=%s cos=%.3f label=%s",
            argument.id, candidate.id, similarity, label,
        )
        if is_duplicate(label):
            return False, f"duplicate of {candidate.id} ({label}, cos={similarity:.3f})"

    # Only a passing argument is worth a vector: a rejected one is filtered out
    # of every future candidate set anyway, so storing it is 12KB nobody reads.
    # DO NOTHING rather than a plain insert because re-running the check at a
    # bumped version reaches here with the vector already stored.
    await db.execute(
        insert(ArgumentEmbedding)
        .values(argument_id=argument.id, model=EMBEDDING_MODEL, vector=vector)
        .on_conflict_do_nothing(constraint="uq_argument_embedding_model")
    )

    max_cos = candidates[0][1] if candidates else 0.0
    detail = f"unique (candidates={len(candidates)}, max_cos={max_cos:.3f})"
    if len(candidates) > len(judged):
        detail += f", truncated at {MAX_JUDGED_CANDIDATES} — passed on partial evidence"
    return True, detail
