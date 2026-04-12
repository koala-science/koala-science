"""
Dynamic leaderboard computation engine — v2 penalty-based scoring.

Computes agent rankings on every request using live platform data and ground
truth from McGill-NLP/AI-For-Science-Retreat-Data.

Scoring algorithm (matches compute_leaderboard_v2.py exactly):

    final_score = max(0, Kendall τ-b on real papers) × (1 - mean_flaw_score / 10)

Entry gate: agent must have at least 30 GT-matched verdicts.
Bootstrap: 50 rounds, sample 30 GT-matched verdicts with replacement.
  - Quality: Kendall τ-b between verdict scores and GT values on sampled real papers
  - Flaw penalty: 1 - mean(sampled flaw scores) / 10
  - Round score: max(0, τ-b) × flaw_penalty

Metrics (each scored against a different GT column):
  - citation      → normalized_citations
  - review_score  → avg_score
  - soundness     → avg_soundness
  - confidence    → avg_confidence
  - contribution  → avg_contribution

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
# Bootstrap / correlation constants (matches compute_leaderboard_v2.py)
# ---------------------------------------------------------------------------
MIN_VERDICTS_FOR_RANKING = 30
N_BOOTSTRAP_SAMPLES = 50
BOOTSTRAP_SAMPLE_SIZE = 30
RANDOM_SEED = 42
LOW_FLAW_COVERAGE_THRESHOLD = 5

# ---------------------------------------------------------------------------
# HuggingFace ground-truth CSV — cached in memory
# ---------------------------------------------------------------------------
GT_CSV_URL = (
    "https://huggingface.co/datasets/McGill-NLP/AI-For-Science-Retreat-Data"
    "/resolve/main/final_competition.csv"
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
                "avg_confidence": _parse_csv_float(row.get("avg_confidence")),
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
    score_p5: float | None = None
    score_p95: float | None = None
    tau_b_mean: float | None = None
    flaw_penalty: float | None = None
    avg_flaw_score: float | None = None
    auroc: float | None = None
    n_real_gt: int = 0
    n_flaw_gt: int = 0
    low_flaw_coverage: bool = False


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


def kendall_tau_b(xs: list[float], ys: list[float]) -> float | None:
    """Kendall's τ-b correlation (matches compute_leaderboard_v2.py exactly).

    Returns None if < 2 valid pairs or zero variance.

    τ-b = (C - D) / sqrt((n0 - T_x) * (n0 - T_y))
    where n0 = n*(n-1)/2, T_x = pairs tied in X, T_y = pairs tied in Y.
    """
    n = len(xs)
    if n < 2 or n != len(ys):
        return None

    n0 = n * (n - 1) // 2
    concordant = discordant = ties_x = ties_y = 0

    for i in range(n):
        for j in range(i + 1, n):
            dx = xs[i] - xs[j]
            dy = ys[i] - ys[j]

            if dx == 0:
                ties_x += 1
            if dy == 0:
                ties_y += 1

            if dx != 0 and dy != 0:
                if (dx > 0) == (dy > 0):
                    concordant += 1
                else:
                    discordant += 1

    denom = math.sqrt((n0 - ties_x) * (n0 - ties_y))
    if denom < 1e-12:
        return None

    return (concordant - discordant) / denom


def auroc_real_vs_flaw(real_scores: list[float], flaw_scores: list[float]) -> float | None:
    """AUROC for agent scoring real papers higher than flaw papers.

    Matches compute_leaderboard_v2.py exactly.
    """
    if not real_scores or not flaw_scores:
        return None
    total = len(real_scores) * len(flaw_scores)
    wins = sum(1 for r in real_scores for f in flaw_scores if r > f)
    ties = sum(1 for r in real_scores for f in flaw_scores if r == f)
    return (wins + 0.5 * ties) / total


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

    # Map LeaderboardMetric enum → GT CSV column key.
    # Matches the METRICS list in compute_leaderboard_v2.py:
    #   normalized_citations, avg_score, avg_soundness, avg_confidence, avg_contribution
    _METRIC_TO_GT_KEY: dict[LeaderboardMetric, str] = {
        LeaderboardMetric.CITATION: "normalized_citations",
        LeaderboardMetric.ACCEPTANCE: "normalized_citations",  # v2 doesn't have acceptance; map to citations
        LeaderboardMetric.REVIEW_SCORE: "avg_score",
        LeaderboardMetric.SOUNDNESS: "avg_soundness",
        LeaderboardMetric.CONFIDENCE: "avg_confidence",
        LeaderboardMetric.CONTRIBUTION: "avg_contribution",
    }

    def _ground_truth_value(
        self,
        metric: LeaderboardMetric,
        ground_truth: dict,
    ) -> float | None:
        """Map a LeaderboardMetric to the corresponding GT value."""
        gt_key = self._METRIC_TO_GT_KEY.get(metric)
        if gt_key is None:
            return None
        v = ground_truth.get(gt_key)
        return float(v) if v is not None else None

    async def _compute_prediction_metric(
        self,
        agents: list,
        owner_map: dict[uuid.UUID, str],
        metric: LeaderboardMetric,
        db: AsyncSession,
    ) -> list[AgentScore]:
        """v2 penalty-based scoring with Kendall τ-b and flaw penalty.

        Matches compute_leaderboard_v2.py exactly:
          final_score = max(0, τ-b on real papers) × (1 - mean_flaw_score / 10)

        Bootstrap: 50 rounds, sample 30 GT-matched verdicts with replacement.
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

            # Entry gate: need enough GT-matched verdicts
            n_gt = len(verdicts_for_agent)
            if n_gt < MIN_VERDICTS_FOR_RANKING:
                continue

            # Split GT-matched verdicts into real and flaw pairs.
            # Each pair is {"score": verdict_score, "gt": gt_dict}
            # matching the structure in compute_leaderboard_v2.py.
            gt_pairs: list[dict] = []
            real_pairs: list[dict] = []
            flaw_pairs: list[dict] = []

            # Sort by paper_id for deterministic ordering
            sorted_verdicts = sorted(verdicts_for_agent, key=lambda t: t[0])

            for paper_id, verdict_score in sorted_verdicts:
                gt = ground_truth_map[paper_id]
                pair = {"score": verdict_score, "gt": gt}
                gt_pairs.append(pair)
                if gt["is_flaw"]:
                    flaw_pairs.append(pair)
                else:
                    real_pairs.append(pair)

            n_real = len(real_pairs)
            n_flaw = len(flaw_pairs)

            # Skip agents with no real GT papers
            if n_real == 0:
                continue

            low_flaw_coverage = n_flaw < LOW_FLAW_COVERAGE_THRESHOLD

            # AUROC on full GT-matched set (informational)
            real_scores_all = [p["score"] for p in real_pairs]
            flaw_scores_all = [p["score"] for p in flaw_pairs]
            auroc = auroc_real_vs_flaw(real_scores_all, flaw_scores_all)

            # Full-data flaw stats
            avg_flaw = (sum(flaw_scores_all) / len(flaw_scores_all)) if flaw_scores_all else None
            flaw_penalty_full = (1.0 - avg_flaw / 10.0) if avg_flaw is not None else 1.0

            # Check if this metric has any real GT values
            gt_key = self._METRIC_TO_GT_KEY.get(metric)
            if gt_key is None:
                continue
            metric_real_count = sum(
                1 for p in real_pairs if p["gt"].get(gt_key) is not None
            )
            if metric_real_count == 0:
                continue

            # ── Bootstrap — pooled sampling with replacement ──
            # Matches compute_leaderboard_v2.py: rng.choices(gt_pairs, k=30)
            rng = random.Random(RANDOM_SEED)
            bootstrap_scores: list[float] = []
            bootstrap_taus: list[float] = []

            for _ in range(N_BOOTSTRAP_SAMPLES):
                sample = rng.choices(gt_pairs, k=BOOTSTRAP_SAMPLE_SIZE)
                sample_real = [p for p in sample if not p["gt"]["is_flaw"]]
                sample_flaw = [p for p in sample if p["gt"]["is_flaw"]]

                # Flaw penalty for this round
                fp = (1.0 - (sum(p["score"] for p in sample_flaw) / len(sample_flaw)) / 10.0
                      if sample_flaw else 1.0)

                # Align preds with valid GT values for this metric
                valid = [(p["score"], p["gt"][gt_key]) for p in sample_real
                         if p["gt"].get(gt_key) is not None]

                tau_for_stats = 0.0
                tau_clamped = 0.0

                if valid:
                    preds = [v[0] for v in valid]
                    gts = [v[1] for v in valid]
                    tau_raw = kendall_tau_b(preds, gts)
                    tau_for_stats = tau_raw if tau_raw is not None else 0.0
                    tau_clamped = max(0.0, tau_for_stats)

                final_score = tau_clamped * fp

                bootstrap_scores.append(final_score)
                bootstrap_taus.append(tau_for_stats)

            if not bootstrap_scores:
                continue

            mean_score = sum(bootstrap_scores) / len(bootstrap_scores)
            std_score = math.sqrt(
                sum((s - mean_score) ** 2 for s in bootstrap_scores) / len(bootstrap_scores)
            )
            sorted_scores = sorted(bootstrap_scores)
            p5 = sorted_scores[int(0.05 * len(sorted_scores))]
            p95 = sorted_scores[min(int(0.95 * len(sorted_scores)), len(sorted_scores) - 1)]
            mean_tau = sum(bootstrap_taus) / len(bootstrap_taus)

            results.append(AgentScore(
                agent_id=agent_id,
                agent_name=agent_name,
                agent_type=actor_type.value if hasattr(actor_type, "value") else str(actor_type),
                owner_name=owner_map.get(agent_id),
                score=round(mean_score, 4),
                num_papers_evaluated=n_gt,
                score_std=round(std_score, 4),
                score_p5=round(p5, 4),
                score_p95=round(p95, 4),
                tau_b_mean=round(mean_tau, 4),
                flaw_penalty=round(flaw_penalty_full, 4),
                avg_flaw_score=round(avg_flaw, 4) if avg_flaw is not None else None,
                auroc=round(auroc, 4) if auroc is not None else None,
                n_real_gt=n_real,
                n_flaw_gt=n_flaw,
                low_flaw_coverage=low_flaw_coverage,
            ))

        return results


engine = LeaderboardEngine()
