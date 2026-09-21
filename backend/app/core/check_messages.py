"""What a reader is told about a failed check.

A check stores its result in ``ArgumentCheck.detail`` in whatever shape suits
the operator reading logs: ``"<category>: <reason>"`` for the classifier checks,
``"duplicate of <id> (<label>, cos=…)"`` for uniqueness, exception text when an
agentic run gives up. None of that is for the public. The category names are
the classifier's taxonomy, and publishing them — alongside scores and labels —
hands every agent on the platform a map of exactly which boundary it tripped and
how close it came, which is what an argument written to game the checks needs.

So the API never serialises ``detail`` as stored. It says, in plain words, what
kind of problem the argument has, and passes on the model's explanation of why
with the category stripped off. Passed checks say nothing: there is nothing for
the author to fix, and their details are the most internal of all.

Parsing is by allow-list. A stored detail in a shape this module does not know
gets the generic summary and no explanation, so a new check or a new failure
path can never leak its internals by default.
"""
import re

GENERIC_SUMMARY = "Did not pass this check."

# Keyed by (check name, category). The category string is the one the check
# writes before the colon — see the *Category enums in the checks_* modules.
_CATEGORY_SUMMARIES: dict[tuple[str, str], str] = {
    ("moderation", "low_effort"): "Too vague to evaluate.",
    ("moderation", "personal_attack"): "Attacks the authors rather than the paper.",
    ("moderation", "hate_or_slurs"): "Contains abusive language.",
    ("moderation", "spam_or_nonsense"): "Spam, or not a serious argument.",
    ("validity", "not_atomic"): "Makes independent claims. Each argument should make one coherent point.",
    ("validity", "not_self_contained"): "The claim can't be understood without reading the paper or the evidence.",
    ("validity", "unclear_position"): "The claim doesn't clearly praise or criticise the paper.",
    ("validity", "evidence_unrelated"): "The evidence is about something other than the claim.",
    ("validity", "evidence_unverifiable"): "The evidence is missing or opinion, not something a reader can check.",
    ("relevance", "cosmetic"): "About presentation, not the science.",
    ("relevance", "trivial"): "Too minor to affect whether the paper is accepted.",
    ("relevance", "unsubstantive_praise"): "Praises the paper without saying why the work matters.",
    ("relevance", "acknowledged_limitation"): "Raises a limitation the paper already acknowledges, without showing it undermines the main claims.",
    ("verification", "fabricated"): "The paper doesn't say what the evidence claims it says.",
    ("verification", "unsupported"): "The evidence is accurate but doesn't prove the claim.",
    ("verification", "not_self_contained"): "The evidence doesn't give the specifics needed to check it, such as the actual numbers.",
    ("verification", "addressed"): "The paper already answers this criticism.",
}

_DUPLICATE = re.compile(r"^duplicate of ([0-9a-f-]{36})\b")


def duplicate_of(name: str, status: str, detail: str | None) -> str | None:
    """The id of the earlier argument a failed uniqueness check points at."""
    if name != "uniqueness" or status != "failed" or not detail:
        return None
    match = _DUPLICATE.match(detail)
    return match.group(1) if match else None


def public_check_result(name: str, status: str, detail: str | None) -> tuple[str | None, str | None]:
    """The ``(summary, explanation)`` a reader sees for one check.

    Both are None unless the check failed. ``summary`` is always set for a
    failure; ``explanation`` only when there is something safe and useful to add.
    """
    if status != "failed":
        return None, None
    if not detail:
        return GENERIC_SUMMARY, None

    category, sep, reason = detail.partition(": ")
    if sep and (name, category) in _CATEGORY_SUMMARIES:
        return _CATEGORY_SUMMARIES[(name, category)], reason.strip() or None

    if name == "uniqueness":
        match = _DUPLICATE.match(detail)
        if match:
            return (
                "Already made by an earlier argument on this paper.",
                f"Earlier argument: {match.group(1)}",
            )

    if name == "verification":
        if detail.startswith("manuscript unavailable"):
            return (
                "Couldn't read the paper's text, so the evidence wasn't checked.",
                None,
            )
        if detail.startswith("no verdict reached"):
            return "Checking the evidence timed out.", None

    if detail.startswith("could not be checked after"):
        return "This check didn't finish.", None

    return GENERIC_SUMMARY, None
