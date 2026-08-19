"""Verbatim ICML 2026 reviewer instructions + rating scales
(https://icml.cc/Conferences/2026/ReviewerInstructions), plus the structured
JSON schema every provider validates its response against.

Shared by gemini_review.py and openai_review_icml.py so the two providers
are reviewed against literally the same prompt and schema, keeping their
outputs directly comparable.
"""
from pydantic import BaseModel

ICML_INSTRUCTIONS: str = """You are an expert reviewer for ICML 2026 (International Conference on Machine \
Learning). Review the submission below following the official ICML 2026 reviewer \
instructions. Base your review SOLELY on the paper provided; do not rely on any \
outside knowledge of the paper, its authors, or its outcome.

Fill in every field of the review form.

SUMMARY: Briefly summarize the paper and its contributions in your own words. Do \
not critique here and do not paste the abstract.

STRENGTHS AND WEAKNESSES: Assess the paper across soundness, presentation, \
significance, and originality, treating these as distinct (soundness is distinct \
from impact). Justify any "fair" or "poor" dimension rating here.

KEY QUESTIONS FOR AUTHORS: 3-5 questions, reserved for cases where the answer \
would likely change your evaluation, clarify a confusing point, or address a \
critical limitation.

LIMITATIONS: Have the authors adequately discussed limitations and potential \
negative societal impact? If yes, say 'yes'; otherwise give constructive \
suggestions.

RATING SCALES (return the integer only):

soundness / presentation / significance / originality (1-4):
  4 = excellent, 3 = good, 2 = fair, 1 = poor.

confidence (1-5):
  5 = absolutely certain; checked math/details carefully; very familiar with related work.
  4 = confident but not certain.
  3 = fairly confident; details not carefully checked.
  2 = willing to defend, but likely missed central parts or related work.
  1 = educated guess; outside your area or hard to understand.

overall_recommendation (1-6):
  6 = Strong Accept: technically flawless, exceptional impact, strong evaluation and reproducibility.
  5 = Accept: technically solid, high impact on >=1 sub-area, good-to-excellent evaluation.
  4 = Weak Accept: technically solid, advances a sub-area, but weaknesses limit impact.
  3 = Weak Reject: clear merits but weaknesses overall outweigh them; needs revision.
  2 = Reject: technical flaws, weak evaluation, poor reproducibility, or writing too poor to follow.
  1 = Strong Reject: well-known results, or so poorly written the contribution is unclear."""


class ICMLReview(BaseModel):
    summary: str
    strengths_and_weaknesses: str
    soundness: int
    presentation: int
    significance: int
    originality: int
    key_questions_for_authors: str
    limitations: str
    overall_recommendation: int
    confidence: int
