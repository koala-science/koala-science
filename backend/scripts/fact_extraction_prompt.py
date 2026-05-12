"""Prompt and parser for per-comment fact extraction.

Adapted from Demfier/reviewertoo's
``src/prompts_icml/metareviewer/default.py`` → ``fact_extraction``.
Differences from the original:

- The ``<rebuttal>`` and ``<post_rebuttal_discussion>`` blocks are removed
  (Koala has no rebuttal phase).
- Scope is narrowed from "all reviews concatenated" to a single comment.
- A ``[NO FACTS]`` sentinel is added so comments that yield zero facts
  still produce a deterministic, parseable response.

Co-located with ``extract_facts.py`` to keep offline-only code out of
``app/``.
"""

PROMPT_VERSION: str = "v3"


SYSTEM_PROMPT: str = (
    "You are an expert peer-review analyst. Your job is to extract "
    "ARGUMENTS — review-bearing arguments — from a reviewer's comment "
    "on an academic paper. An argument is a single, self-contained "
    "critique or praise of the paper, with all the evidence it relies "
    "on bundled INTO the argument. You are NOT extracting facts. You "
    "are NOT decomposing claims. You are extracting whole arguments, "
    "one per emitted item. A reader should be able to read a single "
    "extracted argument and know exactly what the reviewer was arguing "
    "and why."
)


USER_PROMPT_TEMPLATE: str = """\
You will be given a single review comment that {agent_name} wrote about \
an academic paper. Your task is to extract REVIEW-BEARING ARGUMENTS — \
self-contained units of critique or praise.

# The unit of extraction is the ARGUMENT, not the atomic fact

An argument is a coherent reason the reviewer gives for or against the \
paper. It bundles:

- The reviewer's evaluative point (what is being criticized or praised).
- The factual evidence supporting it (the data, the citation, the \
  arithmetic, the missing baseline).
- Any inferential link tying evidence to evaluation.

The argument MUST be checkable: a reader with the paper in hand could \
in principle verify whether the argument holds.

Do NOT split an argument into atomic facts. If the reviewer's point is \
"the paper's biological-fidelity claim is undermined because FlyGM was \
trained by MLP-distillation rather than directly on biology", emit ONE \
fact containing that whole argument — not three (paper claims X, was \
trained on Y, therefore Z).

# Worked examples

## Example 1 — short, single-evidence argument

Comment: "Contributions are limited because they fail to cite related \
work like Jing et al. (2024)."

Extract:
[FACT]: The paper does not cite Jing et al. (2024), which the reviewer \
treats as a gap in related-work coverage.

(One argument, one [FACT] line. Do not split into "The paper does not \
cite Jing et al." plus "Contributions are limited" — the judgment alone \
is not checkable, and the citation gap alone loses why it matters.)

## Example 2 — quantitative comparison

Comment: "Table 2 shows 92% on ImageNet, which clearly beats the SOTA \
baseline (Smith 2021 at 89%)."

Extract:
[FACT]: The paper reports 92% accuracy on ImageNet in Table 2, which \
beats Smith (2021)'s reported 89% on the same benchmark.

(One argument. The two numbers belong together: their relationship is \
the praise.)

## Example 3 — chained inference (the FlyGM case)

Comment: "The authors claim FlyGM mirrors biological functional \
segregation. However, FlyGM was trained via imitation learning of an \
artificial MLP expert, which itself was trained on biological data. \
Consequently, FlyGM is structurally distilling the representations of \
an artificial network. Claims mapping these internal dynamics to \
'neurophysiological processes' should be stated with more caution."

Extract:
[FACT]: The paper claims FlyGM's internal representations mirror \
biological functional segregation, but FlyGM was trained by imitation \
of an artificial MLP expert (not directly on biological data), so \
FlyGM is structurally distilling an artificial network's representations \
rather than biology directly — weakening the paper's biological-fidelity \
claim.

(One [FACT] line containing the whole argument. Do NOT emit "The MLP \
expert was trained on biological data" as a standalone fact — by itself \
it carries no review weight.)

## Example 4 — forensic arithmetic

Comment: "Table 1 reports MissParam=60.87% and LongContext=54.54% for \
LLaMA-3.1-8B. But Appendix B.1.1 Table 7 says n=22 for MissParam and \
n=23 for LongContext. 60.87% of 22 is 13.39 successes (not an integer), \
while 60.87% of 23 = 14 exactly; 54.54% of 23 is 12.54 (not an integer), \
while 54.55% of 22 = 12 exactly. The two cells appear to have been \
swapped."

Extract:
[FACT]: Table 1's reported LLaMA-3.1-8B values (MissParam 60.87%, \
LongContext 54.54%) are not achievable as integer-success ratios at the \
sample sizes given in Appendix B.1.1 Table 7 (n=22 and n=23 \
respectively), but exactly match the SWAPPED configuration (14/23 = \
60.87% for LongContext, 12/22 = 54.55% for MissParam), suggesting the \
two cells were swapped.

(One [FACT] line. Splitting this into "sample sizes are n=22 and n=23", \
"60.87% requires 13.39 successes", "14/23 = 60.87%", etc. destroys the \
argument.)

## Example 5 — multiple independent arguments

Comment: "The proof of Theorem 2 silently drops the IID assumption at \
step 4. Separately, the experimental section omits a Smith 2021 \
baseline, which is the standard comparison for this task."

Extract:
[FACT]: The proof of Theorem 2 silently drops the IID assumption at \
step 4 without justification, breaking the chain of reasoning that the \
theorem relies on.
[FACT]: The paper omits a comparison against Smith (2021), which is the \
standard baseline for this task.

(Two arguments — distinct critiques about different parts of the paper \
— emitted as two [FACT] lines.)

## Example 6 — pure judgment with no factual hook

Comment: "The paper is well-written and the figures are clear."

Extract: [NO FACTS]

(No checkable claims supporting any specific evaluation.)

# Rules

1. Each [FACT] line is ONE ARGUMENT — a complete unit of critique or \
   praise with its evidence and inference bundled in.
2. Do NOT split arguments into atomic checkable claims. If the \
   reviewer's chain has 5 logical steps, emit them as a single \
   compound fact, not 5 facts.
3. SPLIT only when the reviewer makes truly independent arguments \
   (different critiques about different aspects of the paper).
4. Each fact must be SELF-CONTAINED: a reader who has not seen the \
   comment can understand the full argument (mention paper title, \
   table/section/equation numbers, baseline names, etc., as needed).
5. STRIP pure judgment wrappers ("limited", "impressive", "weak") — \
   keep the factual content and the logical link that makes it a \
   review-bearing argument.
6. NEVER emit context facts (method summaries, definitions, \
   reformulations of paper content) UNLESS they are bundled into an \
   argument as evidence.
7. Output ONLY [FACT] lines, one per argument. No headers, no \
   numbering, no commentary.
8. If the comment contains no review-bearing arguments (pure opinion, \
   pure question, empty acknowledgement, etc.), respond with exactly \
   ``[NO FACTS]`` and nothing else.

<paper_title>
{paper_title}
</paper_title>

<comment>
{comment_text}
</comment>

Extract the review-bearing arguments now.\
"""


def parse_facts(raw_response: str) -> list[str]:
    """Parse the model output into a list of fact strings.

    Returns ``[]`` if the response is exactly ``[NO FACTS]`` (after a
    strip) or if no ``[FACT]:`` lines are present. Lines that don't
    start with ``[FACT]:`` are silently ignored — the prompt asks the
    model not to emit them, but real models stray.
    """
    stripped = raw_response.strip()
    if stripped == "[NO FACTS]":
        return []

    facts: list[str] = []
    for line in stripped.splitlines():
        line = line.strip()
        if not line.startswith("[FACT]:"):
            continue
        fact = line[len("[FACT]:") :].strip()
        if fact:
            facts.append(fact)
    return facts
