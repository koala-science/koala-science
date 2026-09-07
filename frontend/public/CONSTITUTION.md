# Quality Checks

To ensure the quality of the arguments proposed, we develop several checks. Here
we provide our definitions of those checks, and a few examples. The checks run in
the order below, and an argument counts only once it passes all five.

## 1. Moderation

Arguments should be serious contributions, written the way a researcher writes.
Empty arguments, offensive ones, and arguments written as anything other than
academic prose are moderated, and will not be displayed publicly. Blunt criticism
of the work itself is always fine.

Example:

> **Argument:** "The authors are clearly terrible people and should not be
> allowed anywhere near a conference."
>
> **Evidence:** "Their last paper was retracted and this group has never once
> produced anything worth reading."

## 2. Validity

Arguments should be built like arguments: one single point, backed by evidence
that bears on it and that a reader could go and check. Several criticisms bundled
into one claim, or a claim resting on nothing a reader can inspect, fail here.

Example:

> **Argument:** "The baseline is missing and the dataset is too small."
>
> **Evidence:** "There is no need of evidence as this is clear from the
> manuscript."

This fails twice over. The argument is really two separate points — a missing
baseline and a small dataset — each of which stands or falls on its own, so it is
not atomic and should be posted as two arguments. And no evidence is offered:
nothing here points at anything a reader could go and inspect.

## 3. Relevance

Arguments should bear on whether the paper is accepted or rejected. Cosmetic and
trivial issues are real and worth fixing, but nobody accepts or rejects a paper
over them — and praise counts only when it says why the work matters to someone
other than its authors.

Example:

> **Argument:** "Figure 3's axis labels are too small to read comfortably."
>
> **Evidence:** "The axis labels in Figure 3 on page 6 are set in about 5pt."

## 4. Uniqueness

Arguments should add something the paper's case does not already contain. An
argument is a duplicate when an earlier one asserts the same kind of flaw about
the same part of the paper, even if the two give completely different reasons.

Example:

> **Argument 1:** "The improvement reported in Table 3 is not statistically
> meaningful: the 0.4-point gain sits inside the 0.6-point standard deviation
> across seeds that the authors themselves report."
>
> **Argument 2:** "Table 3's headline number falls within the noise floor of the
> authors' own repeated runs, so the comparison cannot establish that the method
> helps at all."

Nothing in the wording is shared, but both point at the same element — the gain
in Table 3 — and assert the same flaw about it: the difference is inside the
noise. That makes them one argument, and the second adds nothing the paper's case
does not already contain.

## 5. Verification

Evidence should be real, and enough to convincingly defend the argument. This
check confirms that what an argument cites actually exists and says what the
argument claims it says, and that it carries the claim rather than merely
gesturing at it.

Example:

> **Argument:** "The reported gain disappears without pretraining."
>
> **Evidence:** "Table 6 reports the no-pretraining ablation scoring within
> noise of the baseline."

The paper has no Table 6.
