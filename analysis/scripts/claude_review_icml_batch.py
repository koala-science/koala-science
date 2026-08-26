"""Generate ICML-style reviews with a Claude model via the Message Batches API.

Batch counterpart to claude_review_icml.py, at 50% of sync pricing. Same
ICML_INSTRUCTIONS prompt, same ICMLReview schema, no tools -- so the resulting
dataset drops into the same plots as the sync-path baselines.

Two deliberate differences from the sync script:

  * max_tokens is raised from 8192. Sonnet 5 runs adaptive thinking by default,
    which overran 8192 on 6 of 30 pilot papers; a truncated response fails
    ICMLReview validation and is lost. max_tokens is a ceiling rather than a
    target, so raising it changes nothing for responses that already fit.
  * output_config is built explicitly. batches.create cannot take
    output_format=ICMLReview -- the pydantic class reaches the JSON encoder and
    raises. It is built with the SDK's own transform_schema so the wire bytes
    match what beta.messages.parse sends, and a test pins that equality.

Run from the analysis/ directory:
    ANTHROPIC_API_KEY=$ANTHROPIC_API_KEY .venv/bin/python \
        scripts/claude_review_icml_batch.py submit --model claude-sonnet-5 --dry-run
    ... submit --model claude-sonnet-5
    ... status --model claude-sonnet-5
    ... fetch  --model claude-sonnet-5 --cleanup
"""
import argparse
import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import anthropic
from anthropic.lib._parse._transform import transform_schema
from pydantic import TypeAdapter

from icml_review_prompt import ICML_INSTRUCTIONS, ICMLReview
from claude_review_icml import (
    PRICING,
    ROOT,
    ensure_pdf,
    load_papers,
    out_path,
)

BETAS = ["files-api-2025-04-14", "structured-outputs-2025-12-15"]
BATCH_DISCOUNT = 0.5
UPLOAD_CONCURRENCY = 8
MAX_TOKENS = 16000


def state_path(model: str) -> Path:
    return ROOT / "data" / f"anthropic_batch_state_{model}.json"


def save_state(model: str, state: dict) -> None:
    state_path(model).write_text(json.dumps(state, indent=2))


def load_state(model: str) -> dict | None:
    path = state_path(model)
    if not path.exists():
        return None
    return json.loads(path.read_text())


def other_model_states(model: str) -> list[Path]:
    return [p for p in (ROOT / "data").glob("anthropic_batch_state_*.json")
            if p != state_path(model)]


def file_id_cache_path() -> Path:
    return ROOT / "data" / "anthropic_file_ids.json"


def load_file_ids() -> dict[str, str]:
    path = file_id_cache_path()
    if not path.exists():
        return {}
    return json.loads(path.read_text())


def save_file_ids(mapping: dict[str, str]) -> None:
    file_id_cache_path().write_text(json.dumps(mapping, indent=2))


def sync_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    price = PRICING[model]
    return (input_tokens * price["input"] + output_tokens * price["output"]) / 1_000_000


def batch_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    return sync_cost(model, input_tokens, output_tokens) * BATCH_DISCOUNT


def icml_output_config() -> dict:
    return {"format": {"type": "json_schema",
                       "schema": transform_schema(TypeAdapter(ICMLReview).json_schema())}}


def build_request(paper: dict, model: str, file_id: str) -> dict:
    return {
        "custom_id": paper["paper_id"],
        "params": {
            "model": model,
            "max_tokens": MAX_TOKENS,
            "system": ICML_INSTRUCTIONS,
            "output_config": icml_output_config(),
            "messages": [{"role": "user", "content": [
                {"type": "document", "source": {"type": "file", "file_id": file_id}},
                {"type": "text", "text": f"Title: {paper['title']}\n\n"
                                         f"Abstract: {paper['abstract']}"},
            ]}],
        },
    }


def _review_text(message) -> str:
    for block in message.content:
        if block.type == "text":
            return block.text
    raise ValueError(f"no text block (stop_reason={message.stop_reason})")


def parse_result(custom_id: str, result, papers_by_id: dict, model: str) -> dict:
    paper = papers_by_id[custom_id]
    base = {"paper_id": paper["paper_id"], "forum_id": paper["forum_id"],
            "title": paper["title"], "model": model}

    if result.type != "succeeded":
        if result.type == "errored":
            err = result.error.error
            return {**base, "status": "error",
                    "error": f"errored: {err.type}: {err.message}"}
        return {**base, "status": "error", "error": result.type}

    try:
        review = ICMLReview.model_validate_json(_review_text(result.message))
    except Exception as exc:
        return {**base, "status": "error", "error": f"{type(exc).__name__}: {exc}"}

    return {**base, "status": "ok", "review": review.model_dump(),
            "usage": {"input": result.message.usage.input_tokens,
                      "output": result.message.usage.output_tokens}}


def merge_into_dataset(path: Path, records: list[dict]) -> list[dict]:
    """Batch records supersede same-paper records already in the file, except
    that a failure never displaces a review that already succeeded -- otherwise
    re-fetching would undo repairs made by a sync re-run of the failures."""
    existing = {}
    if path.exists():
        for line in path.read_text().splitlines():
            rec = json.loads(line)
            existing[rec["paper_id"]] = rec
    for rec in records:
        prior = existing.get(rec["paper_id"])
        if prior and prior["status"] == "ok" and rec["status"] != "ok":
            continue
        existing[rec["paper_id"]] = rec
    return list(existing.values())


def _client() -> anthropic.Anthropic:
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        sys.exit("set $ANTHROPIC_API_KEY (e.g. from backend/.env)")
    return anthropic.Anthropic(api_key=api_key)


def _upload_pdfs(client: anthropic.Anthropic, papers: list[dict]) -> dict[str, str]:
    from tqdm import tqdm

    mapping = load_file_ids()
    todo = [p for p in papers if p["pdf_uuid"] not in mapping]
    print(f"PDFs: {len(papers)} needed, {len(papers) - len(todo)} already uploaded, "
          f"{len(todo)} to upload")
    if not todo:
        return mapping

    def upload(paper: dict) -> tuple[str, str]:
        path = ensure_pdf(paper["pdf_uuid"])
        uploaded = client.beta.files.upload(
            file=(f"{paper['pdf_uuid']}.pdf", path.read_bytes(), "application/pdf"),
            betas=BETAS)
        return paper["pdf_uuid"], uploaded.id

    with ThreadPoolExecutor(max_workers=UPLOAD_CONCURRENCY) as pool:
        for uuid, file_id in tqdm(pool.map(upload, todo), total=len(todo),
                                  desc="upload", unit="pdf"):
            mapping[uuid] = file_id
            save_file_ids(mapping)
    return mapping


def cmd_submit(args: argparse.Namespace) -> None:
    model = args.model
    if model not in PRICING:
        sys.exit(f"no pricing entry for {model} -- add one to PRICING before running")

    papers = load_papers(None)
    if args.limit:
        papers = papers[:args.limit]
    print(f"papers in cohort: {len(papers)}")

    if args.dry_run:
        file_ids = load_file_ids()
        reqs = [build_request(p, model, file_ids.get(p["pdf_uuid"], "file_DRYRUN"))
                for p in papers]
        blob = json.dumps(reqs)
        print(f"dry run: {len(reqs)} requests, {len(blob)/1048576:.2f} MB serialised")
        print(f"  max_tokens={MAX_TOKENS}  betas={BETAS}")
        print("no network calls made")
        return

    client = _client()
    file_ids = _upload_pdfs(client, papers)
    reqs = [build_request(p, model, file_ids[p["pdf_uuid"]]) for p in papers]
    batch = client.beta.messages.batches.create(requests=reqs, betas=BETAS)
    save_state(model, {
        "batch_id": batch.id,
        "papers": [{"paper_id": p["paper_id"], "forum_id": p["forum_id"],
                    "title": p["title"]} for p in papers],
    })
    print(f"submitted batch {batch.id}  status={batch.processing_status}")
    print(f"check with: {sys.argv[0]} status --model {model}")


def cmd_status(args: argparse.Namespace) -> None:
    state = load_state(args.model)
    if not state:
        sys.exit(f"no batch state for {args.model} -- run submit first")
    batch = _client().beta.messages.batches.retrieve(state["batch_id"], betas=BETAS)
    c = batch.request_counts
    print(f"batch {batch.id}\n  status:    {batch.processing_status}")
    print(f"  requests:  {c.succeeded} succeeded, {c.processing} processing, "
          f"{c.errored} errored, {c.canceled} canceled, {c.expired} expired")
    if batch.processing_status == "ended":
        print(f"  fetch with: {sys.argv[0]} fetch --model {args.model}")


def cmd_fetch(args: argparse.Namespace) -> None:
    model = args.model
    state = load_state(model)
    if not state:
        sys.exit(f"no batch state for {model} -- run submit first")

    client = _client()
    batch = client.beta.messages.batches.retrieve(state["batch_id"], betas=BETAS)
    if batch.processing_status != "ended":
        sys.exit(f"batch is {batch.processing_status}, not ended -- nothing to fetch yet")

    submitted = {p["paper_id"]: p for p in state["papers"]}
    records = [parse_result(r.custom_id, r.result, submitted, model)
               for r in client.beta.messages.batches.results(state["batch_id"], betas=BETAS)]

    if len(records) != len(submitted):
        returned = {r["paper_id"] for r in records}
        missing = [pid for pid in submitted if pid not in returned]
        print(f"WARNING: batch returned {len(records)} records for "
              f"{len(submitted)} requests -- {len(missing)} papers have no result")
        for pid in missing[:10]:
            print(f"    missing: {pid} {submitted[pid]['title'][:50]}")

    out = out_path(model)
    merged = merge_into_dataset(out, records)
    out.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in merged))

    ok = [r for r in records if r["status"] == "ok"]
    errors = [r for r in records if r["status"] == "error"]
    spend = batch_cost(model, sum(r["usage"]["input"] for r in ok),
                       sum(r["usage"]["output"] for r in ok))
    print(f"wrote {out} ({len(merged)} records)\n  ok={len(ok)}  errors={len(errors)}")
    print(f"  batch spend: ${spend:.2f}")
    if errors:
        print(f"  re-run the {len(errors)} failures through the sync script:")
        print(f"    .venv/bin/python scripts/claude_review_icml.py --model {model}")

    if args.cleanup:
        blocking = other_model_states(model)
        if blocking:
            print("  keeping the uploaded PDFs, still referenced by "
                  f"{', '.join(b.name for b in blocking)}")
        else:
            mapping = load_file_ids()
            deleted = 0
            while mapping:
                _, file_id = mapping.popitem()
                client.beta.files.delete(file_id, betas=BETAS)
                save_file_ids(mapping)
                deleted += 1
            print(f"  deleted {deleted} uploaded PDFs")
        state_path(model).unlink()
        print("  deleted this model's state")


def cmd_smoke(args: argparse.Namespace) -> None:
    """Fire the exact batch request params at the sync endpoint for a few
    papers, to prove the explicit output_config works before the full batch."""
    model = args.model
    if model not in PRICING:
        sys.exit(f"no pricing entry for {model} -- add one to PRICING before running")
    client = _client()
    papers = load_papers(None)[:args.n]
    file_ids = _upload_pdfs(client, papers)

    spend = 0.0
    for paper in papers:
        params = build_request(paper, model, file_ids[paper["pdf_uuid"]])["params"]
        resp = client.beta.messages.create(**params, betas=BETAS)
        review = ICMLReview.model_validate_json(_review_text(resp))
        spend += sync_cost(model, resp.usage.input_tokens, resp.usage.output_tokens)
        print(f"\n{paper['title'][:60]}")
        print(f"  overall={review.overall_recommendation} conf={review.confidence} "
              f"sound={review.soundness} pres={review.presentation} "
              f"signif={review.significance} orig={review.originality}")
        print(f"  tokens: in={resp.usage.input_tokens} out={resp.usage.output_tokens} "
              f"(cap {MAX_TOKENS})  stop={resp.stop_reason}")
    print(f"\nsmoke check spent ~${spend:.2f} at sync rates")


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="command", required=True)

    submit = sub.add_parser("submit")
    submit.add_argument("--model", required=True)
    submit.add_argument("--dry-run", action="store_true")
    submit.add_argument("--limit", type=int)
    submit.set_defaults(func=cmd_submit)

    status = sub.add_parser("status")
    status.add_argument("--model", required=True)
    status.set_defaults(func=cmd_status)

    fetch = sub.add_parser("fetch")
    fetch.add_argument("--model", required=True)
    fetch.add_argument("--cleanup", action="store_true")
    fetch.set_defaults(func=cmd_fetch)

    smoke = sub.add_parser("smoke")
    smoke.add_argument("--model", required=True)
    smoke.add_argument("--n", type=int, default=3)
    smoke.set_defaults(func=cmd_smoke)

    args = p.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
