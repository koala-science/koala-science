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

Arguments should be one coherent piece of praise or criticism, backed by
evidence that proves its point and that a reader could check. The argument's
thesis must be self-contained: someone who has not read the paper can fully
understand the thesis, and what sort of evidence exists to back it, without
needing to read the paper or the evidence section. This means that acronyms are not accepted, except
for universally known and accepted ones such as AI, ML, RL or GPU, and neither
are vague arguments that give no intuition about the evidence that will be
provided. An argument's thesis can itself have more than one constituent, as
long as they are chained into a coherent argument that would not hold without
all of its constituents. The argument should clearly be either positive or
negative about the paper, without the need to read the evidence.

Example:

> **Argument:** "The baseline is missing and the dataset is too small."
>
> **Evidence:** "There is no need for evidence, as this is clear from the
> manuscript."

This fails twice over. The argument is really two separate points, each of which
stands on its own. And no evidence is offered: nothing here points at anything a
reader could go and inspect.

In contrast:

> **Argument:** "The baseline is missing, and previous papers have shown that it
> is quite hard to beat."
>
> **Evidence:** "Doe et al. (2020) have shown that the baseline X is simple and
> extremely hard to beat. In fact, the community has adopted this baseline, as
> seen in K et al. and J et al."

This would pass the check, as the argument makes one claim and is clear without
needing to read the paper. At the same time, it provides its evidence in the
evidence section.

## 3. Relevance

Arguments should inform whether the paper should be accepted or rejected.
Cosmetic and trivial issues are not a reason to accept or reject a paper. Praise
counts only when the contribution matters to a community larger than its
authors. A critique should go against the main claims of the paper. This can
include limitations the authors mention, if they substantially undermine the
central claim of the paper; otherwise, acknowledged limitations are not
considered valid.

Example:

> **Argument:** "Figure 3's axis labels are too small to read comfortably."
>
> **Evidence:** "The axis labels in Figure 3 on page 6 are set in about 5pt."

This would not pass the check. Another example:

> **Argument:** "The authors acknowledge that they only test on three pre-trained
> models, which cannot guarantee that the method will work on every possible
> model."
>
> **Evidence:** "The limitations section explicitly acknowledges …"

This would not pass the check either, as the argument raises a point the authors
have already addressed. To be relevant, the argument would have to make the case
for why this limitation substantially undermines the main claims of the paper.

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
means the evidence must be verified, and must be enough to fully support the
argument for the vast majority of readers. For example, strongly worded
arguments must provide correspondingly strong evidence to convince a reader. The
critique must also not already be thoroughly addressed in the paper, as the
authors may already have taken measures that convincingly answer it. If the
argument relies on citations that the paper uses, the check verifies that those
citations are grounded in the original cited paper, that is, that the cited work
fully supports how the paper uses it. Arguments should be self-contained in their
evidence, and not rely on readers going to the paper to understand them. For
example, to claim a "dramatic reduction" in some value, the evidence must give
the specific numbers. As a guide, verification is expected to be an easy
process: if the evidence does not allow for easy verification (some readers
might not be convinced within five minutes of reading it), the argument fails
verification.

Example:

> **Argument:** "The reported gain disappears without pretraining."
>
> **Evidence:** "Table 6 reports the no-pretraining ablation scoring within
> noise of the baseline."

This would not pass, as it is not clear what "disappears" means: no numbers are
given, and only Table 6 is referenced.
