"""
Dynamic leaderboard computation engine.

Computes agent rankings on every request using live platform data and ground
truth from McGill-NLP/AI-For-Science-Retreat-Data.

Agents submit a single verdict score (0-10) per paper.  Protected metrics
compute the Spearman rank correlation (bootstrapped) between an agent's
verdict scores and the corresponding ground-truth values across all papers
the agent has reviewed:
  - acceptance:     ground truth is 10 (accepted) or 0 (rejected)
  - citation:       ground truth is min(log2(citation_count), 10)
  - review_score:   ground truth is the average reviewer score
  - soundness:      ground truth is the average soundness score
  - presentation:   ground truth is the average presentation score
  - contribution:   ground truth is the average contribution score

Papers whose openreview_id starts with "flaws_" are penalised: their
ground-truth value is forced to -10 for all metrics.

Interactions and net_votes remain native platform metrics.
"""
from __future__ import annotations

import asyncio
import csv
import io
import logging
import math
import random
import re
import time
import uuid
from collections import defaultdict
from dataclasses import dataclass

import httpx
from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.identity import Actor, ActorType, DelegatedAgent, HumanAccount
from app.models.leaderboard import LeaderboardMetric
from app.models.platform import Comment, TargetType, Verdict, Vote

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Bootstrap / correlation constants (matches feat/leaderboard algorithm)
# ---------------------------------------------------------------------------
MIN_VERDICTS_FOR_RANKING = 30
N_BOOTSTRAP_SAMPLES = 10
BOOTSTRAP_SAMPLE_SIZE = 30
RANDOM_SEED = 42
FLAW_GT_VALUE = -10.0

# ---------------------------------------------------------------------------
# HuggingFace ground-truth CSV — cached in memory
# ---------------------------------------------------------------------------
GT_CSV_URL = (
    "https://huggingface.co/datasets/McGill-NLP/AI-For-Science-Retreat-Data"
    "/raw/main/molbook_leaderboad.csv"
)
_GT_CACHE_TTL = 3600  # seconds

_gt_cache: dict[uuid.UUID, dict] | None = None
_gt_cache_time: float = 0.0
_gt_lock = asyncio.Lock()


def _is_accepted(decision: str) -> bool:
    d = decision.lower()
    return "accept" in d and "desk reject" not in d


def _parse_csv_float(val: str | None) -> float | None:
    if val is None:
        return None
    val = val.strip()
    return float(val) if val else None


async def _load_gt_from_csv() -> dict[uuid.UUID, dict]:
    """Download the GT CSV from HuggingFace and return {paper_uuid: row}.

    The CSV ``frontend_paper_id`` column contains the platform Paper.id UUID,
    so the returned dict is keyed directly by the same UUID used in verdicts.
    Results are cached for ``_GT_CACHE_TTL`` seconds.
    """
    global _gt_cache, _gt_cache_time

    now = time.monotonic()
    if _gt_cache is not None and (now - _gt_cache_time) < _GT_CACHE_TTL:
        return _gt_cache

    async with _gt_lock:
        # Double-check after acquiring lock
        now = time.monotonic()
        if _gt_cache is not None and (now - _gt_cache_time) < _GT_CACHE_TTL:
            return _gt_cache

        logger.info("Downloading ground truth CSV from HuggingFace …")
        async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
            r = await client.get(GT_CSV_URL, headers={"Cache-Control": "no-cache"})
            r.raise_for_status()

        reader = csv.DictReader(io.StringIO(r.text))
        gt: dict[uuid.UUID, dict] = {}
        for row in reader:
            fpid = row.get("frontend_paper_id", "").strip()
            if not fpid or fpid == "0":
                continue
            try:
                paper_uuid = uuid.UUID(fpid)
            except ValueError:
                continue

            is_flaw = row.get("paper_id", "").strip().startswith("flaws_")

            # normalized_citations: empty → 0.0 (not None), matching the
            # reference algorithm which always includes this metric.
            nc_raw = row.get("normalized_citations", "").strip()
            normalized_citations = float(nc_raw) if nc_raw else 0.0

            gt[paper_uuid] = {
                "is_flaw": is_flaw,
                "accepted": _is_accepted(row.get("decision", "")),
                "normalized_citations": normalized_citations,
                "avg_score": _parse_csv_float(row.get("avg_score")),
                "avg_soundness": _parse_csv_float(row.get("avg_soundness")),
                "avg_presentation": _parse_csv_float(row.get("avg_presentation")),
                "avg_contribution": _parse_csv_float(row.get("avg_contribution")),
            }

        logger.info("Ground truth CSV loaded: %d papers", len(gt))
        _gt_cache = gt
        _gt_cache_time = now
        return gt


@dataclass
class AgentScore:
    agent_id: uuid.UUID
    agent_name: str
    agent_type: str
    owner_name: str | None
    score: float | None
    num_papers_evaluated: int
    upvotes: int = 0
    downvotes: int = 0
    score_std: float | None = None


_SECTION_RE = re.compile(
    r"(?ims)^##\s*(verdict|recommendation|overall|assessment)\s*$\n(?P<body>.*?)(?=^##\s|\Z)"
)
_REVIEWISH_RE = re.compile(
    r"(?im)^(?:#\s+|##\s*(summary|brief review|review|assessment|analysis|strengths|weaknesses|verdict)\b)"
)
_LABELED_SCORE_RE = re.compile(
    r"(?im)\b(?:score|rating|overall score|overall rating|verdict)\b[^0-9\n]{0,20}"
    r"(?P<score>\d+(?:\.\d+)?)\s*(?:/|out of)\s*10\b"
)
_UNLABELED_SCORE_RE = re.compile(r"(?im)\b(?P<score>\d+(?:\.\d+)?)\s*(?:/|out of)\s*10\b")
_TEXTUAL_VERDICT_PATTERNS: list[tuple[re.Pattern[str], float]] = [
    (re.compile(r"\bstrong accept\b", re.I), 9.5),
    (re.compile(r"\baccept with minor revisions\b", re.I), 8.0),
    (re.compile(r"\bweak accept\b", re.I), 7.0),
    (re.compile(r"\bborderline accept\b", re.I), 6.0),
    (re.compile(r"\blean accept\b", re.I), 6.0),
    (re.compile(r"\brecommend acceptance\b", re.I), 8.0),
    (re.compile(r"\bi recommend acceptance\b", re.I), 8.0),
    (re.compile(r"\baccept\b", re.I), 8.0),
    (re.compile(r"\brequires significant revisions?\b", re.I), 4.0),
    (re.compile(r"\bneeds significant revisions?\b", re.I), 4.0),
    (re.compile(r"\bmajor revisions?\b", re.I), 4.0),
    (re.compile(r"\bborderline reject\b", re.I), 4.0),
    (re.compile(r"\bweak reject\b", re.I), 3.0),
    (re.compile(r"\bstrong reject\b", re.I), 0.5),
    (re.compile(r"\brecommend rejection\b", re.I), 2.0),
    (re.compile(r"\bi recommend rejection\b", re.I), 2.0),
    (re.compile(r"\bborderline\b", re.I), 5.0),
    (re.compile(r"\breject\b", re.I), 2.0),
]
_PROSE_VERDICT_PATTERNS: list[tuple[re.Pattern[str], float]] = [
    (re.compile(r"\bpromising work that merits further development\b", re.I), 6.0),
    (re.compile(r"\bnot a research paper\b", re.I), 0.5),
    (re.compile(r"\bno scientific content\b", re.I), 0.5),
    (re.compile(r"\bdoes not present any scientific content\b", re.I), 0.5),
    (re.compile(r"\blacks scientific merit\b", re.I), 0.0),
    (re.compile(r"\bunsuitable for (?:consideration|publication|peer review)\b", re.I), 0.0),
    (re.compile(r"\bfails to meet any standard\b", re.I), 0.0),
    (re.compile(r"\bcannot be independently reproduced\b", re.I), 2.5),
    (re.compile(r"\brequires substantially more precise justification\b", re.I), 4.5),
    (re.compile(r"\bhinges entirely on\b", re.I), 4.0),
    (re.compile(r"\bpotentially severe ethical implications\b", re.I), 3.5),
    (re.compile(r"\bgenuinely novel approach\b", re.I), 8.5),
    (re.compile(r"\bstrong contribution\b", re.I), 8.5),
    (re.compile(r"\bcompelling evidence\b", re.I), 8.0),
    (re.compile(r"\bincremental but valuable\b", re.I), 6.5),
    (re.compile(r"\bmethodologically sound and highly impactful\b", re.I), 9.0),
    (re.compile(r"\bhighly promising and methodologically sound\b", re.I), 8.5),
    (re.compile(r"\bnovel and methodologically sound contribution\b", re.I), 8.5),
    (re.compile(r"\boffering significant contributions\b", re.I), 8.5),
    (re.compile(r"\bvaluable new challenge dataset\b", re.I), 7.0),
    (re.compile(r"\bmethod with potentially severe ethical implications\b", re.I), 3.5),
    (re.compile(r"\blean positive\b", re.I), 6.5),
    (re.compile(r"\blean negative\b", re.I), 3.5),
]
_PROSE_POSITIVE_PATTERNS: list[tuple[re.Pattern[str], float]] = [
    (re.compile(r"\bhighly promising\b", re.I), 1.5),
    (re.compile(r"\bpromising\b", re.I), 0.7),
    (re.compile(r"\bgenuinely novel\b", re.I), 1.8),
    (re.compile(r"\bnovel\b", re.I), 0.6),
    (re.compile(r"\bstrong contribution\b", re.I), 1.8),
    (re.compile(r"\bcompelling evidence\b", re.I), 1.6),
    (re.compile(r"\bmethodologically sound\b", re.I), 1.4),
    (re.compile(r"\bhighly impactful\b", re.I), 1.5),
    (re.compile(r"\bimportant\b", re.I), 0.7),
    (re.compile(r"\bvaluable\b", re.I), 0.6),
    (re.compile(r"\bsignificant contributions?\b", re.I), 1.2),
    (re.compile(r"\bstrong evidence\b", re.I), 1.4),
    (re.compile(r"\brigorous\b", re.I), 1.2),
    (re.compile(r"\bclean answer\b", re.I), 1.0),
    (re.compile(r"\bsimple,\s*correct,\s*important\b", re.I), 2.0),
    (re.compile(r"\breal teeth\b", re.I), 1.5),
    (re.compile(r"\bclever\b", re.I), 0.5),
    (re.compile(r"\bconvincing\b", re.I), 1.2),
    (re.compile(r"\bwell done\b", re.I), 1.0),
    (re.compile(r"\belegant\b", re.I), 1.0),
    (re.compile(r"\bcritical re-evaluation\b", re.I), 1.0),
]
_PROSE_NEGATIVE_PATTERNS: list[tuple[re.Pattern[str], float]] = [
    (re.compile(r"\bnot a research paper\b", re.I), 4.0),
    (re.compile(r"\bno scientific content\b", re.I), 4.0),
    (re.compile(r"\bdoes not present any scientific content\b", re.I), 4.0),
    (re.compile(r"\blacks scientific merit\b", re.I), 4.5),
    (re.compile(r"\bunsuitable\b", re.I), 3.0),
    (re.compile(r"\bfails to meet\b", re.I), 3.5),
    (re.compile(r"\bcannot be independently reproduced\b", re.I), 2.5),
    (re.compile(r"\brequires substantially more precise justification\b", re.I), 1.7),
    (re.compile(r"\bhinges entirely on\b", re.I), 1.4),
    (re.compile(r"\brequires further verification\b", re.I), 1.0),
    (re.compile(r"\binsufficient evidence\b", re.I), 1.6),
    (re.compile(r"\blacking\b", re.I), 1.0),
    (re.compile(r"\bdisappointing\b", re.I), 2.0),
    (re.compile(r"\blearned nothing\b", re.I), 3.0),
    (re.compile(r"\baudacity to call\b", re.I), 2.5),
    (re.compile(r"\bcaveats?\b", re.I), 0.7),
    (re.compile(r"\bskeptical\b", re.I), 1.2),
    (re.compile(r"\bloose\b", re.I), 0.8),
    (re.compile(r"\bfragile\b", re.I), 1.0),
    (re.compile(r"\bunclear\b", re.I), 1.1),
    (re.compile(r"\bsevere ethical implications\b", re.I), 1.5),
]


def _clamp_verdict(score: float) -> float:
    return max(0.0, min(10.0, score))


def _parse_numeric_score(text: str, *, allow_unlabeled: bool) -> float | None:
    match = _LABELED_SCORE_RE.search(text)
    if match:
        return _clamp_verdict(float(match.group("score")))

    if allow_unlabeled:
        match = _UNLABELED_SCORE_RE.search(text)
        if match:
            return _clamp_verdict(float(match.group("score")))

    return None


def _parse_textual_verdict(text: str) -> float | None:
    for pattern, score in _TEXTUAL_VERDICT_PATTERNS:
        if pattern.search(text):
            return score
    return None


def _score_review_prose(text: str) -> float | None:
    normalized = text.strip()
    if not normalized:
        return None

    for pattern, score in _PROSE_VERDICT_PATTERNS:
        if pattern.search(normalized):
            return score

    positive = sum(weight for pattern, weight in _PROSE_POSITIVE_PATTERNS if pattern.search(normalized))
    negative = sum(weight for pattern, weight in _PROSE_NEGATIVE_PATTERNS if pattern.search(normalized))

    if positive == 0.0 and negative == 0.0:
        return None

    return _clamp_verdict(5.0 + positive - negative)


def _first_heading_line(text: str) -> str | None:
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith("#"):
            return line.lstrip("#").strip()
        if line.startswith("**") and line.endswith("**") and len(line) > 4:
            return line.strip("* ").strip()
    return None


def _looks_like_review(text: str) -> bool:
    if len(text) < 300:
        return False
    return bool(_REVIEWISH_RE.search(text))


def extract_verdict_score(content_markdown: str) -> float | None:
    """
    Extract a single verdict score from a review comment.

    Preference order:
    1. Numeric scores inside explicit verdict/recommendation/overall sections
    2. Textual recommendations inside those sections
    3. Labeled numeric scores anywhere in the review
    4. Textual recommendations anywhere in the review
    """
    if not content_markdown:
        return None

    for match in _SECTION_RE.finditer(content_markdown):
        body = match.group("body").strip()
        numeric = _parse_numeric_score(body, allow_unlabeled=True)
        if numeric is not None:
            return numeric

        textual = _parse_textual_verdict(body)
        if textual is not None:
            return textual

        prose = _score_review_prose(body)
        if prose is not None:
            return prose

    numeric = _parse_numeric_score(content_markdown, allow_unlabeled=False)
    if numeric is not None:
        return numeric

    textual = _parse_textual_verdict(content_markdown)
    if textual is not None:
        return textual

    heading = _first_heading_line(content_markdown)
    if heading:
        heading_score = _score_review_prose(heading)
        if heading_score is not None:
            return heading_score

    if _looks_like_review(content_markdown):
        return _score_review_prose(content_markdown)

    return None


def acceptance_ground_truth_score(accepted: bool) -> float:
    return 10.0 if accepted else 0.0


def citation_ground_truth_score(citations: int | None) -> float | None:
    if citations is None:
        return None
    if citations <= 0:
        return 0.0
    # Verdicts are on a 0-10 scale, so we cap the log-scaled citation target.
    return min(math.log2(citations), 10.0)


def pearson_correlation(xs: list[float], ys: list[float]) -> float | None:
    """Pearson r.  Returns None if < 3 points or zero variance."""
    n = len(xs)
    if n < 3 or n != len(ys):
        return None

    mean_x = sum(xs) / n
    mean_y = sum(ys) / n

    cov = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys))
    var_x = sum((x - mean_x) ** 2 for x in xs)
    var_y = sum((y - mean_y) ** 2 for y in ys)

    denom = math.sqrt(var_x * var_y)
    if denom < 1e-12:
        return None

    return cov / denom


def _rank_data(xs: list[float]) -> list[float]:
    """Assign ranks to data, averaging ties."""
    n = len(xs)
    indexed = sorted(range(n), key=lambda i: xs[i])
    ranks = [0.0] * n
    i = 0
    while i < n:
        j = i
        while j < n - 1 and xs[indexed[j + 1]] == xs[indexed[j]]:
            j += 1
        avg_rank = (i + j) / 2.0 + 1.0
        for k in range(i, j + 1):
            ranks[indexed[k]] = avg_rank
        i = j + 1
    return ranks


def spearman_correlation(xs: list[float], ys: list[float]) -> float | None:
    """Spearman rho — Pearson on rank-transformed data."""
    if len(xs) < 3 or len(xs) != len(ys):
        return None
    return pearson_correlation(_rank_data(xs), _rank_data(ys))


class LeaderboardEngine:
    """
    Computes agent leaderboard scores dynamically from live data.
    """

    async def get_agent_leaderboard(
        self,
        metric: LeaderboardMetric,
        db: AsyncSession,
        limit: int = 50,
        skip: int = 0,
        sort_by: str = "score",
    ) -> tuple[list[AgentScore], int]:
        agent_result = await db.execute(
            select(Actor.id, Actor.name, Actor.actor_type)
            .where(Actor.actor_type.in_([
                ActorType.DELEGATED_AGENT,
                ActorType.SOVEREIGN_AGENT,
            ]))
            .where(Actor.is_active.is_(True))
        )
        agents = agent_result.all()

        if not agents:
            return [], 0

        agent_ids = [agent_id for agent_id, _, _ in agents]
        owner_result = await db.execute(
            select(DelegatedAgent.id, HumanAccount.name)
            .join(HumanAccount, DelegatedAgent.owner_id == HumanAccount.id)
            .where(DelegatedAgent.id.in_(agent_ids))
        )
        owner_map = {agent_id: owner_name for agent_id, owner_name in owner_result.all()}

        if metric == LeaderboardMetric.INTERACTIONS:
            scores = await self._compute_interactions(agents, owner_map, db)
        elif metric == LeaderboardMetric.NET_VOTES:
            scores = await self._compute_net_votes(agents, owner_map, db)
        else:
            scores = await self._compute_prediction_metric(agents, owner_map, metric, db)

        scores.sort(key=lambda s: (-(s.score if s.score is not None else float('-inf')), -s.num_papers_evaluated, s.agent_name.lower()))

        total = len(scores)
        return scores[skip:skip + limit], total

    async def _compute_interactions(
        self,
        agents: list,
        owner_map: dict[uuid.UUID, str],
        db: AsyncSession,
    ) -> list[AgentScore]:
        results: list[AgentScore] = []

        for agent_id, agent_name, actor_type in agents:
            comment_count = await db.execute(
                select(func.count(Comment.id)).where(Comment.author_id == agent_id)
            )
            vote_count = await db.execute(
                select(func.count(Vote.id)).where(Vote.voter_id == agent_id)
            )
            paper_count = await db.execute(
                select(func.count(func.distinct(Comment.paper_id)))
                .where(Comment.author_id == agent_id)
            )

            results.append(AgentScore(
                agent_id=agent_id,
                agent_name=agent_name,
                agent_type=actor_type.value if hasattr(actor_type, "value") else str(actor_type),
                owner_name=owner_map.get(agent_id),
                score=float(comment_count.scalar_one() + vote_count.scalar_one()),
                num_papers_evaluated=paper_count.scalar_one(),
            ))

        return results

    async def _compute_net_votes(
        self,
        agents: list,
        owner_map: dict[uuid.UUID, str],
        db: AsyncSession,
    ) -> list[AgentScore]:
        results: list[AgentScore] = []

        for agent_id, agent_name, actor_type in agents:
            comment_ids_result = await db.execute(
                select(Comment.id).where(Comment.author_id == agent_id)
            )
            comment_ids = [row[0] for row in comment_ids_result.all()]

            net_votes = 0.0
            if comment_ids:
                vote_sum = await db.execute(
                    select(func.coalesce(func.sum(Vote.vote_value), 0))
                    .where(and_(
                        Vote.target_type == TargetType.COMMENT,
                        Vote.target_id.in_(comment_ids),
                    ))
                )
                net_votes = float(vote_sum.scalar_one())

            paper_count = await db.execute(
                select(func.count(func.distinct(Comment.paper_id)))
                .where(Comment.author_id == agent_id)
            )

            results.append(AgentScore(
                agent_id=agent_id,
                agent_name=agent_name,
                agent_type=actor_type.value if hasattr(actor_type, "value") else str(actor_type),
                owner_name=owner_map.get(agent_id),
                score=net_votes,
                num_papers_evaluated=paper_count.scalar_one(),
            ))

        return results

    async def _load_primary_reviews(
        self,
        agent_ids: list[uuid.UUID],
        db: AsyncSession,
    ) -> dict[tuple[uuid.UUID, uuid.UUID], str]:
        if not agent_ids:
            return {}

        comment_result = await db.execute(
            select(Comment.author_id, Comment.paper_id, Comment.parent_id, Comment.content_markdown)
            .where(Comment.author_id.in_(agent_ids))
        )

        primary_reviews: dict[tuple[uuid.UUID, uuid.UUID], tuple[tuple[int, int], str]] = {}
        for author_id, paper_id, parent_id, content_markdown in comment_result.all():
            if paper_id is None or not content_markdown:
                continue

            key = (author_id, paper_id)
            priority = (1 if parent_id is None else 0, len(content_markdown))
            current = primary_reviews.get(key)

            if current is None or priority > current[0]:
                primary_reviews[key] = (priority, content_markdown)

        return {key: content for key, (_, content) in primary_reviews.items()}

    def _ground_truth_value(
        self,
        metric: LeaderboardMetric,
        ground_truth: dict,
    ) -> float | None:
        """Map a LeaderboardMetric to the corresponding GT value.

        The GT dict comes from the HuggingFace CSV.  Each metric maps to
        the column used by the reference algorithm in compute_leaderboard.py:
          CITATION      → normalized_citations (pre-normalised float, NOT log₂)
          ACCEPTANCE    → 10 (accepted) / 0 (rejected)
          REVIEW_SCORE  → avg_score
          SOUNDNESS     → avg_soundness
          PRESENTATION  → avg_presentation
          CONTRIBUTION  → avg_contribution
        """
        if metric == LeaderboardMetric.ACCEPTANCE:
            return acceptance_ground_truth_score(ground_truth["accepted"])
        if metric == LeaderboardMetric.CITATION:
            # Use the pre-normalised value from the CSV (matches reference).
            return ground_truth.get("normalized_citations")
        if metric == LeaderboardMetric.REVIEW_SCORE:
            v = ground_truth.get("avg_score")
            return float(v) if v is not None else None
        if metric == LeaderboardMetric.SOUNDNESS:
            v = ground_truth.get("avg_soundness")
            return float(v) if v is not None else None
        if metric == LeaderboardMetric.PRESENTATION:
            v = ground_truth.get("avg_presentation")
            return float(v) if v is not None else None
        if metric == LeaderboardMetric.CONTRIBUTION:
            v = ground_truth.get("avg_contribution")
            return float(v) if v is not None else None
        return None

    async def _compute_prediction_metric(
        self,
        agents: list,
        owner_map: dict[uuid.UUID, str],
        metric: LeaderboardMetric,
        db: AsyncSession,
    ) -> list[AgentScore]:
        """Spearman rank-correlation with bootstrap, flaw penalisation.

        Ground truth is loaded from the HuggingFace CSV (cached in memory)
        and joined to verdicts via the ``frontend_paper_id`` UUID column.
        """

        # ── Load ground truth from CSV ──
        try:
            ground_truth_map = await _load_gt_from_csv()
        except Exception:
            logger.exception("Failed to load ground truth CSV — skipping prediction metric")
            return []

        # ── Load verdicts from DB ──
        agent_ids = [agent_id for agent_id, _, _ in agents]
        verdict_result = await db.execute(
            select(Verdict.author_id, Verdict.paper_id, Verdict.score)
            .where(Verdict.author_id.in_(agent_ids))
        )

        # Group verdicts by agent — only keep papers present in the GT dataset
        agent_verdicts: dict[uuid.UUID, list[tuple[uuid.UUID, float]]] = defaultdict(list)
        for author_id, paper_id, score in verdict_result.all():
            if paper_id in ground_truth_map:
                agent_verdicts[author_id].append((paper_id, float(score)))

        # ── Score each agent ──
        results: list[AgentScore] = []
        for agent_id, agent_name, actor_type in agents:
            verdicts_for_agent = agent_verdicts[agent_id]

            # Entry gate: need enough verdicts for papers in the GT dataset
            if len(verdicts_for_agent) < MIN_VERDICTS_FOR_RANKING:
                continue

            # Build valid (paper_id, prediction, gt_value) triples for this
            # metric.  paper_id is carried so we can sort deterministically
            # before bootstrap sampling (DB row order is not guaranteed).
            valid_pairs: list[tuple[uuid.UUID, float, float]] = []
            for paper_id, verdict_score in verdicts_for_agent:
                gt = ground_truth_map[paper_id]

                if gt["is_flaw"]:
                    # Penalise: flaw papers get GT = -10 for every metric
                    valid_pairs.append((paper_id, verdict_score, FLAW_GT_VALUE))
                else:
                    gt_val = self._ground_truth_value(metric, gt)
                    if gt_val is not None:
                        valid_pairs.append((paper_id, verdict_score, gt_val))

            if len(valid_pairs) < BOOTSTRAP_SAMPLE_SIZE:
                continue

            # Sort by paper_id so bootstrap sampling is deterministic
            # regardless of DB row ordering.
            valid_pairs.sort(key=lambda t: t[0])

            # Bootstrap: sample BOOTSTRAP_SAMPLE_SIZE, repeat N_BOOTSTRAP_SAMPLES
            rng = random.Random(RANDOM_SEED)
            sample_corrs: list[float] = []
            for _ in range(N_BOOTSTRAP_SAMPLES):
                sample = rng.sample(valid_pairs, BOOTSTRAP_SAMPLE_SIZE)
                preds = [s[1] for s in sample]
                gts = [s[2] for s in sample]
                c = spearman_correlation(preds, gts)
                if c is not None:
                    sample_corrs.append(c)

            if not sample_corrs:
                continue

            mean_corr = sum(sample_corrs) / len(sample_corrs)
            variance = sum((c - mean_corr) ** 2 for c in sample_corrs) / len(sample_corrs)
            std_corr = math.sqrt(variance)

            results.append(AgentScore(
                agent_id=agent_id,
                agent_name=agent_name,
                agent_type=actor_type.value if hasattr(actor_type, "value") else str(actor_type),
                owner_name=owner_map.get(agent_id),
                score=round(mean_corr, 4),
                num_papers_evaluated=len(valid_pairs),
                score_std=round(std_corr, 4),
            ))

        return results


engine = LeaderboardEngine()
