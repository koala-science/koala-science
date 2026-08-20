"""Run the `relevance` prompt against the labelled cases.

    python -m evals.run_relevance
    python -m evals.run_relevance --repeat 7 --tier anchor

Costs real Gemini calls. See README.md for how to read a disagreement.
"""
import argparse
import asyncio
from collections import Counter
from types import SimpleNamespace

from app.core.checks_relevance import relevance_check
from app.core.gemini import CheckUnavailableError
from app.models.platform import ArgumentPosition
from evals.relevance_cases import CASES, PAPER_ABSTRACT, PAPER_TITLE, TIERS, Case


async def _verdict(case: Case, sem: asyncio.Semaphore) -> tuple[bool | None, str]:
    """Drive the real check, so the eval cannot drift from what ships.

    Only an outage is absorbed: anything else — a changed signature, a bad case —
    is a bug in the harness and should crash rather than be reported per-case.
    """
    argument = SimpleNamespace(
        claim=case.claim,
        evidence=case.evidence,
        position=ArgumentPosition(case.position),
        paper=SimpleNamespace(title=PAPER_TITLE, abstract=PAPER_ABSTRACT),
    )
    async with sem:
        try:
            return await relevance_check(None, argument)
        except CheckUnavailableError as exc:
            return None, f"unavailable: {exc}"


async def score(cases: list[Case], concurrency: int) -> int:
    sem = asyncio.Semaphore(concurrency)
    results = await asyncio.gather(*(_verdict(c, sem) for c in cases))

    regressions, errors = [], []
    for case, (got, detail) in zip(cases, results):
        if got is None:
            mark, expected_s = "!!", "-"
            errors.append(case.id)
        elif case.expected is None:
            mark, expected_s = "??", "open"
        else:
            expected_s = "pass" if case.expected else "fail"
            mark = "ok" if got == case.expected else "XX"
            if mark == "XX":
                regressions.append(case.id)
        got_s = "----" if got is None else ("pass" if got else "fail")
        print(f"[{mark}] {case.id:28s} {case.tier:8s} "
              f"expected={expected_s:4s} got={got_s:4s} detail={detail}")
        if mark != "ok":
            print(f"     note: {case.note}")

    print()
    if errors:
        print(f"ERRORS ({len(errors)}): {', '.join(errors)}")
    if regressions:
        print(f"REGRESSIONS ({len(regressions)}): {', '.join(regressions)}")
    if not errors and not regressions:
        print("no regressions")
        return 0
    return 1


async def stability(cases: list[Case], repeat: int, concurrency: int) -> int:
    sem = asyncio.Semaphore(concurrency)
    jobs = [(c, _verdict(c, sem)) for c in cases for _ in range(repeat)]
    results = await asyncio.gather(*(job for _, job in jobs))

    tally: dict[str, Counter] = {c.id: Counter() for c in cases}
    for (case, _), (got, _detail) in zip(jobs, results):
        tally[case.id]["error" if got is None else ("pass" if got else "fail")] += 1

    split, errored = [], []
    for case in cases:
        counts = tally[case.id]
        real = {k: v for k, v in counts.items() if k != "error"}
        stable = len(real) == 1
        if not stable:
            split.append(case.id)
        if counts["error"]:
            errored.append(case.id)
        bar = "  ".join(f"{k}={v}" for k, v in sorted(counts.items()))
        print(f"[{'stable' if stable else 'SPLIT '}] {case.id:28s} {case.tier:8s} {bar}")

    print()
    if errored:
        print(f"cases with at least one error: {', '.join(errored)}")
    dead = [c.id for c in cases if not any(
        k != "error" and v for k, v in tally[c.id].items())]
    if dead:
        print(f"NOTHING RAN ({len(dead)}): {', '.join(dead)}")
        return 1

    unstable_anchors = [c.id for c in cases if c.tier == "anchor" and c.id in split]
    if unstable_anchors:
        print(f"ANCHORS SPLIT ({len(unstable_anchors)}): {', '.join(unstable_anchors)}")
        print("A clear case that is not unanimous means the prompt has lost its grip.")
        return 1
    print(f"{len(split)}/{len(cases)} split: {', '.join(split) or 'none'}"
          f"  (no anchors among them)")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--repeat", type=int, default=1,
                    help="runs per case; >1 reports stability instead of scoring")
    ap.add_argument("--tier", choices=TIERS, help="restrict to one tier")
    ap.add_argument("--concurrency", type=int, default=6)
    args = ap.parse_args()

    cases = CASES if args.tier is None else [c for c in CASES if c.tier == args.tier]
    print(f"{len(cases)} case(s), {args.repeat} run(s) each\n{'=' * 78}")
    if args.repeat > 1:
        return asyncio.run(stability(cases, args.repeat, args.concurrency))
    return asyncio.run(score(cases, args.concurrency))


if __name__ == "__main__":
    raise SystemExit(main())
