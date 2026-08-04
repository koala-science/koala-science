"""Multi-paper argument-coverage pipeline: koala vs ReviewerToo vs Gemini
(PeerReviewBench), generalizing the single-paper ConPress pilot
(plots/coverage_argument_budget.py) to N papers.

Unlike the original pilot, comparisons are WITHIN-method only (koala args
vs koala args, never koala vs reviewertoo) -- the coverage metric ("how
many distinct arguments does this method surface") only ever needs
same-method judgments; the original pilot judged cross-method pairs too
and never used them, which was wasted judge cost.

Stages (checkpointed; each writes a file so expensive steps run once):

  collect : pull koala comment_facts + reviewertoo (pre-decomposed via
            reviewertoo_decompose.py) + gemini (parsed "Item N" blocks)
            per paper -> args.json
  embed   : embed every argument (gemini-embedding-001), list WITHIN-METHOD
            candidate pairs above --threshold -> pairs.json
  judge   : run the CMU 4-way judge (similarity_prompts.py) on candidate
            pairs above --judge-threshold, thinking on -> clusters.json
  plot    : per-paper distinct-argument accumulation curves, averaged
            across papers with a bootstrap 95% CI -> png

Run from the analysis/ directory:
    GEMINI_API_KEY=$(grep '^GEMINI_API_KEY=' ../backend/.env | cut -d= -f2-) \
        .venv/bin/python scripts/coverage_pipeline.py <stage> --sample data/coverage_sample_5_papers.json --tag sample5
"""
import argparse
import asyncio
import itertools
import json
import re
import sys
from pathlib import Path

import psycopg

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(Path(__file__).parent / "judges"))

EMBED_MODEL = "gemini-embedding-001"
JUDGE_MODEL = "gemini-2.5-flash"

SAME_LABELS = {
    "same subject, same argument, same evidence",
    "same subject, same argument, different evidence",
}


def out_path(tag: str, name: str) -> Path:
    return ROOT / "data" / f"coverage_{tag}_{name}"


def _load_jsonl(path: Path) -> list[dict]:
    with path.open() as f:
        return [json.loads(l) for l in f]


def load_sample(sample_path: Path) -> list[str]:
    return json.load(sample_path.open())


def _parse_items(review: str) -> list[str]:
    texts = []
    for m in re.finditer(r"^##\s*Item\s+\d+:?\s*(.*)$", review, re.MULTILINE):
        start = m.end()
        nxt = re.search(r"^##\s*Item\s+\d+", review[start:], re.MULTILINE)
        body = review[start: start + nxt.start()] if nxt else review[start:]
        text = (m.group(1) + "\n" + body).strip()
        if text:
            texts.append(text)
    return texts


# --------------------------------------------------------------------------
# collect
# --------------------------------------------------------------------------

def stage_collect(sample_path: Path, tag: str, sources: set[str]) -> None:
    paper_ids = load_sample(sample_path)
    pid_set = set(paper_ids)
    args = []

    if "koala" in sources:
        with psycopg.connect("postgresql:///coalescence_snapshot") as conn, conn.cursor() as cur:
            cur.execute("""
                SELECT c.paper_id::text, cf.fact_text
                FROM comment_fact cf JOIN comment c ON c.id = cf.comment_id
                WHERE c.paper_id = ANY(%s::uuid[])
            """, (paper_ids,))
            for paper_id, text in cur.fetchall():
                args.append({"paper_id": paper_id, "source": "koala", "text": text})

    if "reviewertoo" in sources:
        rt_path = ROOT / "data" / f"reviewertoo_decomposed_{tag}.jsonl"
        if not rt_path.exists():
            sys.exit(f"missing {rt_path} -- run reviewertoo_decompose.py first")
        for rec in _load_jsonl(rt_path):
            if rec["paper_id"] in pid_set and rec["status"] == "ok":
                for fact in rec["facts"]:
                    args.append({"paper_id": rec["paper_id"], "source": "reviewertoo", "text": fact})

    if "gemini" in sources:
        for rec in _load_jsonl(ROOT / "data" / "icml_2026_gemini_pb_reviews_gemini-3.1-pro-preview.jsonl"):
            if rec["paper_id"] in pid_set and rec["status"] == "ok":
                for text in _parse_items(rec["review"]):
                    args.append({"paper_id": rec["paper_id"], "source": "gemini", "text": text})

    if "peerreviewbench" in sources:
        pb_files = [
            "icml_2026_gemini_pb_reviews_gemini-3.1-pro-preview.jsonl",
            "icml_2026_gemini_pb_reviews_gemini-3.6-flash.jsonl",
            "icml_2026_gemini_pb_reviews_gemini-2.5-pro.jsonl",
            "icml_2026_gemini_pb_reviews_gemini-3-flash-preview.jsonl",
            "icml_2026_openai_reviews_gpt-4.1-nano.jsonl",
            "icml_2026_openai_reviews_gpt-5.2.jsonl",
            "icml_2026_openai_reviews_gpt-5.4-mini.jsonl",
            "icml_2026_openai_reviews_gpt-5.6-sol.jsonl",
            "icml_2026_claude_reviews_claude-haiku-4-5.jsonl",
            "icml_2026_claude_reviews_claude-sonnet-5.jsonl",
        ]
        for fname in pb_files:
            for rec in _load_jsonl(ROOT / "data" / fname):
                if rec["paper_id"] in pid_set and rec["status"] == "ok":
                    for text in _parse_items(rec["review"]):
                        args.append({"paper_id": rec["paper_id"], "source": "peerreviewbench", "text": text})

    from collections import Counter
    by_paper_source = Counter((a["paper_id"], a["source"]) for a in args)
    print(f"papers: {len(pid_set)}  total args: {len(args)}")
    for p in paper_ids:
        row = {s: by_paper_source.get((p, s), 0) for s in sorted(sources)}
        print(f"  {p}: {row}")

    json.dump({"args": args}, open(out_path(tag, "args.json"), "w"))
    print(f"-> {out_path(tag, 'args.json')}")


# --------------------------------------------------------------------------
# embed
# --------------------------------------------------------------------------

async def stage_embed(threshold: float, tag: str) -> None:
    import os
    from google import genai
    import numpy as np

    blob = json.load(open(out_path(tag, "args.json")))
    args = blob["args"]
    client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])

    vecs = []
    B = 100
    for i in range(0, len(args), B):
        batch = [a["text"] for a in args[i:i + B]]
        resp = await asyncio.to_thread(
            client.models.embed_content, model=EMBED_MODEL, contents=batch)
        vecs.extend([e.values for e in resp.embeddings])
    X = np.array(vecs)
    X = X / np.linalg.norm(X, axis=1, keepdims=True)
    sim = X @ X.T

    n = len(args)
    pairs = []
    for i, j in itertools.combinations(range(n), 2):
        a, b = args[i], args[j]
        if a["paper_id"] != b["paper_id"] or a["source"] != b["source"]:
            continue  # WITHIN-method, WITHIN-paper only
        if sim[i, j] >= threshold:
            pairs.append([i, j, round(float(sim[i, j]), 4)])

    total_within = sum(
        1 for i, j in itertools.combinations(range(n), 2)
        if args[i]["paper_id"] == args[j]["paper_id"] and args[i]["source"] == args[j]["source"]
    )
    print(f"args={n}  within-method pairs={total_within}  candidate_pairs(cos>={threshold})={len(pairs)}")
    json.dump({"pairs": pairs, "threshold": threshold}, open(out_path(tag, "pairs.json"), "w"))
    print(f"-> {out_path(tag, 'pairs.json')}")


# --------------------------------------------------------------------------
# judge
# --------------------------------------------------------------------------

def _extract_answer(text: str) -> str | None:
    m = re.findall(r"<answer>(.*?)</answer>", text, re.S | re.I)
    if not m:
        return None
    ans = m[-1].strip().strip('"').lower()
    for lbl in ("same subject, same argument, same evidence",
                "same subject, same argument, different evidence",
                "same subject, different argument", "different subject"):
        if lbl in ans:
            return lbl
    return None


JUDGE_PRICING = {"gemini-2.5-flash": {"input": 0.30, "output": 2.50}}


def _load_judge_progress(path: Path) -> dict[tuple[int, int], str | None]:
    if not path.exists():
        return {}
    done = {}
    for line in path.open():
        rec = json.loads(line)
        done[(rec["i"], rec["j"])] = rec["label"]
    return done


async def stage_judge(judge_threshold: float, tag: str, concurrency: int) -> None:
    import os
    from google import genai
    from similarity_prompts import FOURWAY_SYSTEM_PROMPT, FOURWAY_USER_PROMPT_TEMPLATE
    from tqdm import tqdm

    blob = json.load(open(out_path(tag, "args.json")))
    args = blob["args"]

    titles = {}
    paper_ids = list({a["paper_id"] for a in args})
    with psycopg.connect("postgresql:///coalescence_snapshot") as conn, conn.cursor() as cur:
        cur.execute("SELECT id::text, title, abstract FROM paper WHERE id = ANY(%s::uuid[])",
                    (paper_ids,))
        for pid, title, abstract in cur.fetchall():
            titles[pid] = f"Title: {title}\n\nAbstract: {(abstract or '')[:1800]}"

    all_pairs = [p for p in json.load(open(out_path(tag, "pairs.json")))["pairs"]
                 if p[2] >= judge_threshold]

    # Incremental checkpoint: resume-safe, one line per judged pair, written
    # (and flushed) as each result lands -- a crash mid-run loses at most the
    # in-flight batch, not the whole job, and re-running skips what's done.
    progress_path = out_path(tag, "judge_progress.jsonl")
    done = _load_judge_progress(progress_path)
    todo = [(i, j, s) for i, j, s in all_pairs if (i, j) not in done]
    print(f"pairs: {len(all_pairs)}  already judged: {len(done)}  to judge: {len(todo)}  "
          f"(cos>={judge_threshold}) on {JUDGE_MODEL}")

    if todo:
        client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
        sem = asyncio.Semaphore(concurrency)
        price = JUDGE_PRICING[JUDGE_MODEL]
        cost_usd = 0.0
        counts = {"ok": 0, "error": 0}

        with progress_path.open("a") as pf, tqdm(total=len(todo), unit="pair") as pbar:
            async def judge(i, j):
                nonlocal cost_usd
                a, b = args[i], args[j]
                user = FOURWAY_USER_PROMPT_TEMPLATE.format(
                    paper_text=titles.get(a["paper_id"], ""),
                    reviewer_a=a["source"], reviewer_b=b["source"],
                    item_a=a["text"], item_b=b["text"])
                label = None
                async with sem:
                    for attempt in range(4):
                        try:
                            resp = await asyncio.to_thread(
                                client.models.generate_content, model=JUDGE_MODEL,
                                contents=[{"role": "user", "parts": [{"text": user}]}],
                                config={"system_instruction": FOURWAY_SYSTEM_PROMPT,
                                        "temperature": 0.0})
                            label = _extract_answer(resp.text or "")
                            usage = resp.usage_metadata
                            if usage.prompt_token_count and usage.candidates_token_count:
                                cost_usd += (usage.prompt_token_count * price["input"]
                                             + usage.candidates_token_count * price["output"]) / 1_000_000
                            break
                        except Exception as e:
                            if attempt == 3:
                                tqdm.write(f"  pair ({i},{j}) failed: {e}")
                            else:
                                await asyncio.sleep(2 * (attempt + 1))
                counts["ok" if label is not None else "error"] += 1
                pf.write(json.dumps({"i": i, "j": j, "label": label}) + "\n")
                pf.flush()
                pbar.set_postfix(ok=counts["ok"], err=counts["error"], cost=f"${cost_usd:.3f}")
                pbar.update(1)

            await asyncio.gather(*(judge(i, j) for i, j, s in todo))

        print(f"this run: cost=${cost_usd:.3f}")
        done = _load_judge_progress(progress_path)

    same_pairs = [[i, j] for i, j, s in all_pairs if done.get((i, j)) in SAME_LABELS]
    labeled = sum(1 for i, j, s in all_pairs if done.get((i, j)) is not None)
    print(f"labeled {labeled}/{len(all_pairs)} pairs; same-argument pairs: {len(same_pairs)}")
    json.dump({"same_pairs": same_pairs,
               "args": [{"paper_id": a["paper_id"], "source": a["source"]} for a in args]},
              open(out_path(tag, "clusters.json"), "w"))
    print(f"-> {out_path(tag, 'clusters.json')}")


# --------------------------------------------------------------------------
# plot
# --------------------------------------------------------------------------

METHOD_COLOR = {"koala": "#2c6fbb", "reviewertoo": "#c0392b", "gemini": "#27ae60",
                "peerreviewbench": "#27ae60"}
METHOD_LABEL = {"koala": "Koala Science", "reviewertoo": "Varying Personalities",
                "gemini": "Gemini (PeerReviewBench)",
                "peerreviewbench": "Varying Base Models"}


def stage_plot(tag: str, max_budget_cap: int | None = None) -> None:
    from collections import defaultdict

    import matplotlib.pyplot as plt
    import numpy as np

    blob = json.load(open(out_path(tag, "clusters.json")))
    meta = blob["args"]
    same = set()
    for i, j in blob["same_pairs"]:
        same.add((i, j))
        same.add((j, i))

    rng = np.random.default_rng(0)

    def distinct(idxs: list[int], n_orders: int = 24) -> float:
        idxs = list(idxs)
        total = 0
        for _ in range(n_orders):
            order = list(idxs)
            rng.shuffle(order)
            reps: list[int] = []
            for x in order:
                if all((x, r) not in same for r in reps):
                    reps.append(x)
            total += len(reps)
        return total / n_orders

    by_paper_source: dict[tuple[str, str], list[int]] = defaultdict(list)
    for i, m in enumerate(meta):
        by_paper_source[(m["paper_id"], m["source"])].append(i)

    papers = sorted({p for p, _ in by_paper_source})
    methods = sorted({s for _, s in by_paper_source}, key=lambda s: list(METHOD_COLOR).index(s))

    # per-paper, per-method curve: budget -> mean distinct (averaged over
    # N_BUDGET_DRAWS random subsets), matching the single-paper pilot's method.
    N_BUDGET_DRAWS = 100
    curves: dict[tuple[str, str], dict[int, float]] = {}
    for (pid, src), idxs in by_paper_source.items():
        pool = list(idxs)
        curve = {}
        pool_budget = min(len(pool), max_budget_cap) if max_budget_cap else len(pool)
        for b in range(1, pool_budget + 1):
            acc = 0.0
            for _ in range(N_BUDGET_DRAWS):
                acc += distinct(rng.choice(pool, size=b, replace=False), n_orders=1)
            curve[b] = acc / N_BUDGET_DRAWS
        curves[(pid, src)] = curve

    fig, ax = plt.subplots(figsize=(7, 7))
    if max_budget_cap:
        ax.plot([0, max_budget_cap], [0, max_budget_cap], ":", color="#888888", lw=2,
                label="Perfect Diversity")
    for src in methods:
        max_budget = max(len(by_paper_source[(p, src)]) for p in papers if (p, src) in by_paper_source)
        if max_budget_cap:
            max_budget = min(max_budget, max_budget_cap)
        xs, means, los, his, ns = [], [], [], [], []
        for b in range(1, max_budget + 1):
            vals = [curves[(p, src)][b] for p in papers
                    if (p, src) in curves and b in curves[(p, src)]]
            if not vals:
                continue
            vals = np.array(vals)
            xs.append(b)
            means.append(vals.mean())
            if len(vals) >= 2:
                boot = [rng.choice(vals, size=len(vals), replace=True).mean() for _ in range(1000)]
                los.append(np.percentile(boot, 2.5))
                his.append(np.percentile(boot, 97.5))
            else:
                los.append(vals[0])
                his.append(vals[0])
            ns.append(len(vals))

        color = METHOD_COLOR[src]
        ax.plot(xs, means, "-", color=color, lw=2.5, label=METHOD_LABEL[src])
        ax.fill_between(xs, los, his, color=color, alpha=0.15, linewidth=0)

    ax.set_xlabel("Total Arguments", fontsize=18)
    ax.set_ylabel("Distinct Arguments", fontsize=18)
    ax.tick_params(axis="both", labelsize=14)
    if max_budget_cap:
        ax.set_xlim(0, max_budget_cap)
        ax.set_ylim(0, max_budget_cap)
        ax.set_aspect("equal")
    ax.legend(loc="lower right", fontsize=15)
    ax.grid(alpha=0.3)
    fig.tight_layout()

    png = ROOT / "output" / f"coverage_{tag}.png"
    fig.savefig(png, dpi=150, bbox_inches="tight")
    print(f"-> {png}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("stage", choices=["collect", "embed", "judge", "plot"])
    ap.add_argument("--sample", type=Path)
    ap.add_argument("--tag", required=True)
    ap.add_argument("--threshold", type=float, default=0.6)
    ap.add_argument("--judge-threshold", type=float, default=0.8)
    ap.add_argument("--concurrency", type=int, default=16)
    ap.add_argument("--sources", default="koala,reviewertoo,gemini",
                    help="comma-separated subset of koala,reviewertoo,gemini")
    ap.add_argument("--max-budget", type=int, default=None,
                    help="cap the plot's x-axis (arguments collected) at this budget")
    a = ap.parse_args()
    sources = set(a.sources.split(","))

    if a.stage == "collect":
        stage_collect(a.sample, a.tag, sources)
    elif a.stage == "embed":
        asyncio.run(stage_embed(a.threshold, a.tag))
    elif a.stage == "judge":
        asyncio.run(stage_judge(a.judge_threshold, a.tag, a.concurrency))
    elif a.stage == "plot":
        stage_plot(a.tag, a.max_budget)


if __name__ == "__main__":
    main()
