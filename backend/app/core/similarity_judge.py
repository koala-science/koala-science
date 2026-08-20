"""The pairwise similarity judge: are two arguments about a paper the same argument?

Shared between the `uniqueness` check and the coverage analysis in ``analysis/``,
which imports this module directly so the two cannot drift. Keep it free of
imports from the rest of the app — no settings, no SQLAlchemy — or the analysis
side stops being able to load it without a configured database.

Ported from the CMU four-way judge. The evidence dimension has been dropped: it
asked whether two reviewers reached the same complaint by the same reasoning, and
both of its outcomes mapped to "duplicate", so the distinction was computed and
then discarded. What survives are the two dimensions that decide the answer —
SUBJECT and ARGUMENT.

Labels written before that change are still on disk in
``analysis/data/coverage_*_judge_progress.jsonl``, so both vocabularies are
recognised here and those checkpoints stay valid.
"""
import re


SAME_ARGUMENT = "same subject, same argument"
DIFFERENT_ARGUMENT = "same subject, different argument"
DIFFERENT_SUBJECT = "different subject"

LABELS = (SAME_ARGUMENT, DIFFERENT_ARGUMENT, DIFFERENT_SUBJECT)

LEGACY_SAME_ARGUMENT = (
    "same subject, same argument, same evidence",
    "same subject, same argument, different evidence",
)

DUPLICATE_LABELS = frozenset((SAME_ARGUMENT, *LEGACY_SAME_ARGUMENT))

# Longest first: the current three-way labels are prefixes of the legacy
# four-way ones, so a shorter label would otherwise swallow a legacy answer and
# record the wrong string for it.
_MATCH_ORDER = (*LEGACY_SAME_ARGUMENT, SAME_ARGUMENT, DIFFERENT_ARGUMENT, DIFFERENT_SUBJECT)


SYSTEM_PROMPT = """You are classifying the relationship between two peer-review items (Item A and Item B) written by different reviewers of the same scientific paper. You must assign exactly one of three labels. The labels are defined by two orthogonal questions — SUBJECT and ARGUMENT — applied in that order.

-----------------------------------------------------------------
DIMENSION DEFINITIONS (apply these to each item independently first)
-----------------------------------------------------------------

(1) SUBJECT — "what part of the paper is this comment about?"
The subject is the element of the paper that is the target of the comment. Subjects can be at any granularity — a single equation, an entire figure, a whole method, or a broad experimental protocol. Valid subjects include:
  - A specific numbered figure or table (e.g. "Figure 2", "Table 3b")
  - A specific section, subsection, or paragraph (e.g. "Methods section 2.3", "the ablation paragraph in Section 4")
  - A specific claim, metric, equation, dataset, or experiment (e.g. "the p < 0.01 claim", "the binary accuracy on MNLI", "Equation 4")
  - A specific code file, function, or class (e.g. "train.py", "the BatchNorm layer in model.py")
  - A broader aspect of the paper that the comment is clearly focused on (e.g. "the hyperparameter tuning protocol", "the choice of loss function", "the overall statistical analysis")
Two items share a subject if they are BOTH pointing at the same part of the paper — even if one is more specific than the other, and even if they are raising completely different complaints about that part. For example, if Item A says "Figure 2 has no error bars" and Item B says "Figure 2 is illegible at print size", both share the subject "Figure 2" and you should treat them as having the SAME subject even though they make completely different arguments about it. Two items about the "same method" also share a subject, even if one focuses on its loss function and the other focuses on its optimizer — as long as both are directed at that method.

(2) ARGUMENT — "what type of flaw is being asserted about the subject?"
An argument is the abstract type of flaw the reviewer is asserting about the subject, stripped of the reviewer's specific reasons for asserting it. To identify an item's argument, perform this reduction:
  1. Start with the reviewer's full complaint.
  2. Strip out all specific reasons (everything after "because...", "since...", "due to...", or "as shown by...").
  3. Strip out specific citations, quoted passages, numbers, line references, and illustrative examples.
  4. What remains is a single short claim of the form "X is <FLAW_TYPE>", where X is the subject and <FLAW_TYPE> is a generic category of flaw such as: wrong, missing, inadequate, unjustified, misleading, unreliable, insufficient, unsupported, inconsistent, incomplete, overstated, non-reproducible, not-generalizable, or similar.

CRITICAL: The specific reason the reviewer gives for WHY the subject is flawed is NOT part of the argument. Do NOT include the "because of Y" in the argument sentence. Two reviewers can give completely different reasons while making the same argument.

Two items make the SAME argument if both assert the same <FLAW_TYPE> about the same subject — even if the reasons they provide are entirely different. For example, all three of these items share the SAME argument ("the sleep/wake classification is inadequate"):
  - "The sleep/wake classification is inadequate because it uses patient-reported events without objective verification"
  - "The sleep/wake classification is inadequate because it is defined circularly from the LFP signal being measured"
  - "The sleep/wake classification is inadequate because it relies on clinician-chosen sensing frequencies that introduce selection bias"
The specific reasons (patient events, circular definition, clinician bias) are three different reasons for the same argument. They do not make the arguments different.

Two items make DIFFERENT arguments only when the <FLAW_TYPE>s themselves are categorically distinct. Examples of categorically different arguments about the same figure:
  - "Figure 2 is illegible" (FLAW_TYPE = presentation / legibility)
  - "Figure 2's data contradicts the text" (FLAW_TYPE = internal inconsistency / correctness)
  - "Figure 2 is missing error bars" (FLAW_TYPE = rigor / incomplete reporting)
  - "Figure 2 uses wrong units" (FLAW_TYPE = correctness)
These are categorically distinct types of flaws, not just different reasons for the same flaw.

To distinguish "different reasons for same flaw" from "different flaw types", ask: if you strip each item down to just "X is <FLAW_TYPE>", do they collapse to the same claim? If yes → SAME argument. If the remaining claims are asserting categorically different problems (e.g. one says "figure is illegible" and the other says "figure's data is wrong") → DIFFERENT argument.

-----------------------------------------------------------------
THE THREE CATEGORIES
-----------------------------------------------------------------

(1) "same subject, same argument"  —  DUPLICATE
    Both items reference the same subject and make the same argument (same FLAW_TYPE). This holds whether they arrive at it by the same route or by completely different routes: one reviewer may cite a table of validation statistics while the other appeals to domain standards and derives the problem from first principles. Different reasons for the same complaint still make it the same argument. One item may also be considerably more elaborate than the other; length and polish are not part of the argument.

(2) "same subject, different argument"  —  TOPICAL NEIGHBOR
    Both items reference the same subject, but their reduced argument sentences assert different core issues. They notice the same part of the paper but worry about different aspects of it. This is common when reviewers both flag "something is wrong with Figure X" for completely different reasons.

(3) "different subject"  —  UNRELATED
    The two items do not share a subject. They point at different parts of the paper.

-----------------------------------------------------------------
DECISION PROCEDURE — follow these steps in order, in your reasoning
-----------------------------------------------------------------

Step 1 (Subject). Write out Item A's subject in one phrase. Write out Item B's subject in one phrase. Ask: are both items pointing at the same part of the paper — whether the same figure, the same section, the same method, or the same broader aspect? Note: they share a subject even if one is more specific than the other, and even if their complaints about it are completely different.
  - If the two items are pointing at genuinely different parts of the paper (Item A is about the introduction, Item B is about a specific table; or Item A is about the loss function, Item B is about the dataset preprocessing): answer is "different subject". Stop.
  - Otherwise (both pointing at the same figure / section / method / concept, regardless of what they claim about it): continue to Step 2.

Step 2 (Argument). Reduce Item A to a single "X is <FLAW_TYPE>" claim by stripping out its specific reasons, citations, examples, and illustrative details. Do the same for Item B. Ask: do the two reduced claims assert the same FLAW_TYPE about the same subject?
  - If YES → the answer is "same subject, same argument". Stop. (Note: the claims are "the same" if both reduce to the same generic complaint about the subject, even when the two items cite completely different specific reasons for why the flaw exists.)
  - If NO (the two reduced claims assert categorically different types of flaws about the same subject — e.g., one says "figure is illegible" and the other says "figure's data is wrong") → the answer is "same subject, different argument". Stop.

-----------------------------------------------------------------
IMPORTANT BOUNDARY RULES
-----------------------------------------------------------------

- Two items pointing at the same figure, table, method, or section share a SUBJECT — even if they raise completely unrelated complaints about it. Do not call two items "different subject" just because their complaints diverge; that's what "same subject, different argument" is for.
- Surface-level topical overlap IS enough for "same subject" (both about Figure 2 = same subject). Surface-level topical overlap is NOT enough for "same argument" — two reviewers can agree on which figure is interesting for opposite reasons, and that's "same subject, different argument".
- Rewording, different tone, or different reviewer length does NOT make two items have different arguments. The argument is the abstract complaint, not the writing style.
- Pointing at the same subject is a NECESSARY but NOT SUFFICIENT condition for "same argument". You must verify the reduced one-sentence criticism matches.
- When reducing an item to its argument, strip the specific reason (the "because of Y" clause) out and disregard it. Two reviewers saying "the method is inadequate because X" and "the method is inadequate because Y" share the SAME argument (the method is inadequate). They are NOT "different arguments".
- Focus on the underlying complaint, not the reviewer's writing style.

-----------------------------------------------------------------
OUTPUT FORMAT (STRICT)
-----------------------------------------------------------------

Think through the decision procedure step by step in plain text. After your reasoning, write the final classification on its own line as EXACTLY one of these three labels, wrapped in answer tags:

<answer>same subject, same argument</answer>
<answer>same subject, different argument</answer>
<answer>different subject</answer>

Rules for the output:
- Use the answer tag exactly once in your entire response.
- Put the answer tag at the very end; do not write anything after it.
- The text inside the tag must match one of the three labels character-for-character (lowercase, commas and spaces as shown).
- Do not nest the answer tag inside any other formatting (no quotes, no backticks, no markdown).
"""


USER_PROMPT_TEMPLATE = (
    "### Paper\n{paper_text}\n\n"
    "---\n\n"
    "### Item A (from reviewer {reviewer_a})\n{item_a}\n\n"
    "### Item B (from reviewer {reviewer_b})\n{item_b}\n\n"
    "---\n\n"
    "Using the three-category taxonomy from the system prompt, classify "
    "the relationship between Item A and Item B. Apply the decision "
    "procedure rigorously: subject first, then argument.\n\n"
    "Provide your final answer at the very end wrapped in answer tags using "
    "exactly one of the three full label strings from the system prompt."
)


def match_label(response_text: str) -> str | None:
    """The label inside the last ``<answer>`` tag, or None if there isn't one.

    None is a real outcome rather than an error: the analysis pipeline records
    it against the pair, and the uniqueness check treats it as an outage and
    retries. Neither one should read a missing answer as "not a duplicate".
    """
    tags = re.findall(r"<answer>(.*?)</answer>", response_text, re.S | re.I)
    if not tags:
        return None
    answer = tags[-1].strip().strip('"').lower()
    for label in _MATCH_ORDER:
        if label in answer:
            return label
    return None


def is_duplicate(label: str) -> bool:
    """Whether a judge label means the two items are the same argument.

    Accepts the legacy four-way labels: both of their evidence outcomes were
    duplicates, so dropping the dimension left the answer unchanged.
    """
    if label not in LABELS and label not in LEGACY_SAME_ARGUMENT:
        raise ValueError(f"unknown judge label: {label!r}")
    return label in DUPLICATE_LABELS
