"""Generate ICML-style reviews with an OpenAI model via the Batch API (50% off).

Batch counterpart to openai_review_icml.py. Same ICML_INSTRUCTIONS prompt, same
ICMLReview schema, same max_output_tokens, no tools -- so the resulting dataset
drops into the same plots as the sync-path baselines and is comparable to them.

Why this is a separate ingest flow rather than a --batch flag: a batch input
JSONL is capped at 200 MB, and base64-inlining the PDF cache (1.7 GB) yields
~2.3 GB. So each PDF is uploaded once via the Files API and referenced by
file_id, which shrinks each request to ~5 KB.

Run from the analysis/ directory:
    OPENAI_API_KEY=$OPENAI_API_KEY .venv/bin/python scripts/openai_review_icml_batch.py \
        submit --model gpt-5.2 --dry-run
    ... submit --model gpt-5.2
    ... status --model gpt-5.2
    ... fetch  --model gpt-5.2 --cleanup
"""
import argparse
import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from openai import OpenAI

from icml_review_prompt import ICML_INSTRUCTIONS, ICMLReview
from openai_review_icml import (
    MAX_OUTPUT_TOKENS,
    PRICING,
    ROOT,
    ensure_pdf,
    load_papers,
    out_path,
)

BATCH_ENDPOINT = "/v1/responses"
COMPLETION_WINDOW = "24h"
BATCH_DISCOUNT = 0.5
UPLOAD_CONCURRENCY = 8


def state_path(model: str) -> Path:
    return ROOT / "data" / f"openai_batch_state_{model}.json"


def save_state(model: str, state: dict) -> None:
    state_path(model).write_text(json.dumps(state, indent=2))


def load_state(model: str) -> dict | None:
    path = state_path(model)
    if not path.exists():
        return None
    return json.loads(path.read_text())


def other_model_states(model: str) -> list[Path]:
    return [p for p in (ROOT / "data").glob("openai_batch_state_*.json")
            if p != state_path(model)]


def file_id_cache_path() -> Path:
    return ROOT / "data" / "openai_file_ids.json"


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


def icml_json_schema() -> dict:
    """Hand-built equivalent of what responses.parse(text_format=ICMLReview)
    sends, since the parse helper is unavailable inside a batch request."""
    schema = ICMLReview.model_json_schema()
    schema["additionalProperties"] = False
    return {
        "type": "json_schema",
        "name": "icml_review",
        "strict": True,
        "schema": schema,
    }


def build_request(paper: dict, model: str, file_id: str) -> dict:
    return {
        "custom_id": paper["paper_id"],
        "method": "POST",
        "url": BATCH_ENDPOINT,
        "body": {
            "model": model,
            "max_output_tokens": MAX_OUTPUT_TOKENS,
            "text": {"format": icml_json_schema()},
            "input": [
                {"role": "system", "content": ICML_INSTRUCTIONS},
                {"role": "user", "content": [
                    {"type": "input_file", "file_id": file_id},
                    {"type": "input_text",
                     "text": f"Title: {paper['title']}\n\n"
                             f"Abstract: {paper['abstract']}"},
                ]},
            ],
        },
    }


def _extract_review_text(body: dict) -> str:
    for item in body["output"]:
        if item["type"] == "message":
            return item["content"][0]["text"]
    raise ValueError(f"no message item in output (status={body['status']})")


def parse_output_line(line: dict, papers_by_id: dict, model: str) -> dict:
    paper = papers_by_id[line["custom_id"]]
    base = {"paper_id": paper["paper_id"], "forum_id": paper["forum_id"],
            "title": paper["title"], "model": model}

    if line["error"]:
        return {**base, "status": "error", "error": json.dumps(line["error"])}

    response = line["response"]
    if response["status_code"] != 200:
        return {**base, "status": "error",
                "error": f"http {response['status_code']}: {json.dumps(response['body'])[:300]}"}

    body = response["body"]
    try:
        review = ICMLReview.model_validate_json(_extract_review_text(body))
    except Exception as exc:
        return {**base, "status": "error", "error": f"{type(exc).__name__}: {exc}"}

    return {**base, "status": "ok", "review": review.model_dump(),
            "usage": {"input": body["usage"]["input_tokens"],
                      "output": body["usage"]["output_tokens"]}}


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


def _client() -> OpenAI:
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        sys.exit("set $OPENAI_API_KEY")
    return OpenAI(api_key=api_key)


def _upload_pdfs(client: OpenAI, papers: list[dict]) -> dict[str, str]:
    from tqdm import tqdm

    mapping = load_file_ids()
    todo = [p for p in papers if p["pdf_uuid"] not in mapping]
    print(f"PDFs: {len(papers)} needed, {len(papers) - len(todo)} already uploaded, "
          f"{len(todo)} to upload")
    if not todo:
        return mapping

    def upload(paper: dict) -> tuple[str, str]:
        path = ensure_pdf(paper["pdf_uuid"])
        with path.open("rb") as fh:
            uploaded = client.files.create(file=fh, purpose="user_data")
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

    jsonl_path = ROOT / "data" / f"openai_batch_input_{model}.jsonl"

    if args.dry_run:
        file_ids = load_file_ids()
        lines = [build_request(p, model, file_ids.get(p["pdf_uuid"], "file-DRYRUN"))
                 for p in papers]
        jsonl_path.write_text("".join(json.dumps(r) + "\n" for r in lines))
        size_mb = jsonl_path.stat().st_size / 1048576
        print(f"dry run: wrote {jsonl_path} ({len(lines)} lines, {size_mb:.2f} MB)")
        print("no network calls made")
        return

    client = _client()
    file_ids = _upload_pdfs(client, papers)
    lines = [build_request(p, model, file_ids[p["pdf_uuid"]]) for p in papers]
    jsonl_path.write_text("".join(json.dumps(r) + "\n" for r in lines))
    size_mb = jsonl_path.stat().st_size / 1048576
    print(f"wrote {jsonl_path} ({len(lines)} lines, {size_mb:.2f} MB)")

    with jsonl_path.open("rb") as fh:
        batch_input = client.files.create(file=fh, purpose="batch")
    batch = client.batches.create(
        input_file_id=batch_input.id,
        endpoint=BATCH_ENDPOINT,
        completion_window=COMPLETION_WINDOW,
        metadata={"description": f"ICML 2026 reviews, {model}"},
    )
    save_state(model, {
        "batch_id": batch.id,
        "input_file_id": batch_input.id,
        "papers": [{"paper_id": p["paper_id"], "forum_id": p["forum_id"],
                    "title": p["title"]} for p in papers],
    })
    print(f"submitted batch {batch.id}  status={batch.status}")
    print(f"check with: {sys.argv[0]} status --model {model}")


def cmd_status(args: argparse.Namespace) -> None:
    state = load_state(args.model)
    if not state:
        sys.exit(f"no batch state for {args.model} -- run submit first")
    batch = _client().batches.retrieve(state["batch_id"])
    counts = batch.request_counts
    print(f"batch {batch.id}\n  status:    {batch.status}")
    print(f"  requests:  {counts.completed}/{counts.total} completed, "
          f"{counts.failed} failed")
    if batch.status == "completed":
        print(f"  fetch with: {sys.argv[0]} fetch --model {args.model}")


def _read_result_lines(client: OpenAI, file_id: str | None) -> list[dict]:
    if file_id is None:
        return []
    return [json.loads(line)
            for line in client.files.content(file_id).text.splitlines()]


def cmd_fetch(args: argparse.Namespace) -> None:
    model = args.model
    state = load_state(model)
    if not state:
        sys.exit(f"no batch state for {model} -- run submit first")

    client = _client()
    batch = client.batches.retrieve(state["batch_id"])
    if batch.status != "completed":
        sys.exit(f"batch is {batch.status}, not completed -- nothing to fetch yet")

    submitted = {p["paper_id"]: p for p in state["papers"]}
    lines = (_read_result_lines(client, batch.output_file_id)
             + _read_result_lines(client, batch.error_file_id))
    records = [parse_output_line(line, submitted, model) for line in lines]

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
        print(f"    .venv/bin/python scripts/openai_review_icml.py --model {model}")

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
                client.files.delete(file_id)
                save_file_ids(mapping)
                deleted += 1
            print(f"  deleted {deleted} uploaded PDFs")
        client.files.delete(state["input_file_id"])
        state_path(model).unlink()
        print("  deleted the batch input file and this model's state")


def cmd_smoke(args: argparse.Namespace) -> None:
    """Fire the exact batch request body at the sync endpoint for a few papers,
    to prove the hand-built schema works before spending on the full batch."""
    model = args.model
    if model not in PRICING:
        sys.exit(f"no pricing entry for {model} -- add one to PRICING before running")
    client = _client()
    papers = load_papers(None)[:args.n]
    file_ids = _upload_pdfs(client, papers)

    spend = 0.0
    for paper in papers:
        body = build_request(paper, model, file_ids[paper["pdf_uuid"]])["body"]
        resp = client.responses.create(**body)
        review = ICMLReview.model_validate_json(resp.output_text)
        spend += sync_cost(model, resp.usage.input_tokens, resp.usage.output_tokens)
        print(f"\n{paper['title'][:60]}")
        print(f"  overall={review.overall_recommendation} conf={review.confidence} "
              f"sound={review.soundness} pres={review.presentation} "
              f"signif={review.significance} orig={review.originality}")
        print(f"  summary: {review.summary[:100]}...")
        print(f"  tokens: in={resp.usage.input_tokens} out={resp.usage.output_tokens}")
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
