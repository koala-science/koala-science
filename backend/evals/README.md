# Prompt evals

Checks are prompts, and a prompt has no compile error — it fails by drawing a
line in the wrong place. `tests/` covers the plumbing around each check with the
model stubbed out; these measure the thing the stub hides.

They are not pytest tests: they need a live `GEMINI_API_KEY` and cost real money,
so nothing in CI runs them. `tests/test_relevance_eval_cases.py` does check the
case sets stay structurally sound, which is what rots first.

## Running

`Settings` reads `.env`, so running from `backend/` needs no extra environment.

```bash
.venv/bin/python -m evals.run_relevance
```

Roughly 45 calls on gemini-2.5-flash, a few cents.

`--repeat N` runs each case N times instead, and reports which ones split. Use it
after any prompt change: verdicts on genuinely borderline arguments are not
deterministic, and neither `temperature=0` nor an explicit uncertainty tie-break
fixed that when it was measured. What the repeat mode is really for is confirming
that the *clear* cases stay unanimous.

```bash
.venv/bin/python -m evals.run_relevance --repeat 7 --tier anchor
```

Both modes exit non-zero on a regression, and also when any call failed — a run
that reached nothing must not read as a clean one. Transient Gemini errors run
at a few percent, so an otherwise-green run can still exit 1 with a single
`ERRORS` line; re-run it rather than reading the exit code as a verdict.

## Reading the output

`expected` is a considered judgement, not ground truth. A disagreement is a
question — is the prompt wrong, or is the case wrong? Both have happened:

- `injection` was written to check that a prompt-injection payload in the
  evidence field could not force a pass. It passes, and should: relevance judges
  the claim, and injection is `moderation`'s job. The case was aimed at the
  wrong check.
- `venue-fit` was written as "belongs in a workshop" — a verdict about venue
  rather than science. But its evidence says the contribution combines two
  existing components, which is a real novelty argument, so passing it is
  defensible. The case was badly built.

Both are kept in the `arguable` tier, which is recorded but not scored, because
they document where the boundary actually is.
