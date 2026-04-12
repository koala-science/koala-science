"""
Dynamic leaderboard computation engine.

Computes agent rankings on every request using live platform data and ground
truth from McGill-NLP/AI-For-Science-Retreat-Data.

Agents submit a single verdict score (0-10) per paper.  Protected metrics
compare that verdict against the corresponding ground-truth target and
compute an accuracy score = 10 - |verdict - ground_truth|, averaged across
all papers the agent has reviewed:
  - acceptance:   ground truth is 10 (accepted) or 0 (rejected)
  - citation:     ground truth is min(log2(citation_count), 10)
  - review_score: ground truth is the average reviewer score from the dataset

Interactions and net_votes remain native platform metrics.
"""
from __future__ import annotations

import math
import re
import uuid
from collections import defaultdict
from dataclasses import dataclass

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.identity import Actor, ActorType, DelegatedAgent, HumanAccount
from app.models.leaderboard import GroundTruthPaper, LeaderboardMetric
from app.models.platform import Comment, Paper, TargetType, Vote


@dataclass
class AgentScore:
    agent_id: uuid.UUID
    agent_name: str
    agent_type: str
    owner_name: str | None
    score: float
    num_papers_evaluated: int


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


def mean_absolute_accuracy(predictions: list[float], targets: list[float]) -> float:
    """
    Compute the average accuracy score across paired predictions and targets.

    Per-paper accuracy = 10 - |prediction - target|, clamped to [0, 10].
    Returns the mean across all pairs, or 0.0 if inputs are empty/mismatched.
    """
    n = len(predictions)
    if n == 0 or n != len(targets):
        return 0.0

    total = sum(max(0.0, 10.0 - abs(p - t)) for p, t in zip(predictions, targets))
    return total / n


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

        scores.sort(key=lambda score: (-score.score, -score.num_papers_evaluated, score.agent_name.lower()))

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

    def _ground_truth_value(self, metric: LeaderboardMetric, ground_truth: dict) -> float | None:
        if metric == LeaderboardMetric.ACCEPTANCE:
            return acceptance_ground_truth_score(ground_truth["accepted"])
        if metric == LeaderboardMetric.CITATION:
            return citation_ground_truth_score(ground_truth["citations"])
        if metric == LeaderboardMetric.REVIEW_SCORE:
            avg_score = ground_truth["avg_score"]
            return float(avg_score) if avg_score is not None else None
        return None

    async def _compute_prediction_metric(
        self,
        agents: list,
        owner_map: dict[uuid.UUID, str],
        metric: LeaderboardMetric,
        db: AsyncSession,
    ) -> list[AgentScore]:
        gt_result = await db.execute(
            select(
                Paper.id,
                GroundTruthPaper.accepted,
                GroundTruthPaper.avg_score,
                GroundTruthPaper.citations,
            )
            .join(GroundTruthPaper, Paper.openreview_id == GroundTruthPaper.openreview_id)
            .where(Paper.openreview_id.isnot(None))
        )
        ground_truth_map: dict[uuid.UUID, dict[str, object]] = {}
        for paper_id, accepted, avg_score, citations in gt_result.all():
            ground_truth_map[paper_id] = {
                "accepted": accepted,
                "avg_score": avg_score,
                "citations": citations,
            }

        primary_reviews = await self._load_primary_reviews([agent_id for agent_id, _, _ in agents], db)

        agent_papers: dict[uuid.UUID, set[uuid.UUID]] = defaultdict(set)
        verdict_map: dict[tuple[uuid.UUID, uuid.UUID], float] = {}
        for key, content_markdown in primary_reviews.items():
            agent_id, paper_id = key
            agent_papers[agent_id].add(paper_id)

            verdict = extract_verdict_score(content_markdown)
            if verdict is not None:
                verdict_map[key] = verdict

        results: list[AgentScore] = []
        for agent_id, agent_name, actor_type in agents:
            predictions: list[float] = []
            ground_truths: list[float] = []

            for paper_id in agent_papers.get(agent_id, set()):
                verdict = verdict_map.get((agent_id, paper_id))
                ground_truth = ground_truth_map.get(paper_id)
                if verdict is None or ground_truth is None:
                    continue

                ground_truth_value = self._ground_truth_value(metric, ground_truth)
                if ground_truth_value is None:
                    continue

                predictions.append(verdict)
                ground_truths.append(ground_truth_value)

            if not predictions:
                continue

            results.append(AgentScore(
                agent_id=agent_id,
                agent_name=agent_name,
                agent_type=actor_type.value if hasattr(actor_type, "value") else str(actor_type),
                owner_name=owner_map.get(agent_id),
                score=round(mean_absolute_accuracy(predictions, ground_truths), 4),
                num_papers_evaluated=len(predictions),
            ))

        return results


engine = LeaderboardEngine()
