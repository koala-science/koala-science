import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

import openai_review_icml as sync_mod
from icml_review_prompt import ICML_INSTRUCTIONS, ICMLReview
from openai_review_icml_batch import (
    batch_cost,
    cmd_fetch,
    build_request,
    icml_json_schema,
    load_state,
    merge_into_dataset,
    other_model_states,
    parse_output_line,
    save_state,
    state_path,
    sync_cost,
)

PAPER = {
    "paper_id": "11111111-2222-3333-4444-555555555555",
    "forum_id": "aBcDeF",
    "title": "A Study of Things",
    "abstract": "We study things, and find that they are indeed things.",
    "pdf_uuid": "deadbeef-0000-1111-2222-333333333333",
}
MODEL = "gpt-5.2"
FILE_ID = "file-abc123"


def _body():
    return build_request(PAPER, MODEL, FILE_ID)["body"]


def test_json_schema_is_strict_and_complete():
    fmt = icml_json_schema()
    assert fmt["type"] == "json_schema"
    assert fmt["strict"] is True
    schema = fmt["schema"]
    assert schema["additionalProperties"] is False
    assert set(schema["required"]) == set(ICMLReview.model_fields)


def test_build_request_envelope():
    req = build_request(PAPER, MODEL, FILE_ID)
    assert req["custom_id"] == PAPER["paper_id"]
    assert req["method"] == "POST"
    assert req["url"] == "/v1/responses"


def test_build_request_references_file_id_not_base64():
    blob = json.dumps(_body())
    assert FILE_ID in blob
    assert "base64" not in blob
    assert "file_data" not in blob


def test_build_request_matches_sync_call_params():
    """Parity with openai_review_icml.review_one -- a baseline that differs in
    prompt or token budget measures the harness, not the model."""
    body = _body()
    assert body["model"] == MODEL
    assert body["max_output_tokens"] == sync_mod.MAX_OUTPUT_TOKENS
    assert "tools" not in body

    system, user = body["input"]
    assert system == {"role": "system", "content": ICML_INSTRUCTIONS}
    assert user["role"] == "user"
    file_part, text_part = user["content"]
    assert file_part["type"] == "input_file"
    assert file_part["file_id"] == FILE_ID
    assert text_part["type"] == "input_text"
    assert text_part["text"] == (
        f"Title: {PAPER['title']}\n\nAbstract: {PAPER['abstract']}"
    )


REVIEW = {
    "summary": "s",
    "strengths_and_weaknesses": "sw",
    "soundness": 3,
    "presentation": 3,
    "significance": 2,
    "originality": 2,
    "key_questions_for_authors": "q",
    "limitations": "l",
    "overall_recommendation": 4,
    "confidence": 3,
}


def _ok_line():
    return {
        "custom_id": PAPER["paper_id"],
        "error": None,
        "response": {
            "status_code": 200,
            "body": {
                "output": [
                    {"type": "reasoning", "summary": []},
                    {
                        "type": "message",
                        "content": [{"type": "output_text", "text": json.dumps(REVIEW)}],
                    },
                ],
                "usage": {"input_tokens": 33000, "output_tokens": 1200},
            },
        },
    }


def test_parse_output_line_ok():
    rec = parse_output_line(_ok_line(), {PAPER["paper_id"]: PAPER}, MODEL)
    assert rec["status"] == "ok"
    assert rec["paper_id"] == PAPER["paper_id"]
    assert rec["forum_id"] == PAPER["forum_id"]
    assert rec["title"] == PAPER["title"]
    assert rec["model"] == MODEL
    assert rec["review"] == REVIEW
    assert rec["usage"] == {"input": 33000, "output": 1200}


def test_parse_output_line_record_shape_matches_sync_dataset():
    """load_ai_scores reads these files; keys must match the shipped datasets."""
    rec = parse_output_line(_ok_line(), {PAPER["paper_id"]: PAPER}, MODEL)
    assert set(rec) == {
        "paper_id", "forum_id", "title", "model", "status", "review", "usage",
    }
    ICMLReview.model_validate(rec["review"])


def test_parse_output_line_api_error():
    """Shape of a line in the batch's error_file, not its output_file."""
    line = {
        "custom_id": PAPER["paper_id"],
        "error": {"code": "rate_limit_exceeded", "message": "slow down"},
        "response": None,
    }
    rec = parse_output_line(line, {PAPER["paper_id"]: PAPER}, MODEL)
    assert rec["status"] == "error"
    assert "rate_limit_exceeded" in rec["error"]


def test_parse_output_line_non_200():
    line = _ok_line()
    line["response"]["status_code"] = 500
    line["response"]["body"] = {"error": {"message": "boom"}}
    assert parse_output_line(line, {PAPER["paper_id"]: PAPER}, MODEL)["status"] == "error"


def test_parse_output_line_unparseable_review():
    line = _ok_line()
    line["response"]["body"]["output"][1]["content"][0]["text"] = "not json{"
    rec = parse_output_line(line, {PAPER["paper_id"]: PAPER}, MODEL)
    assert rec["status"] == "error"


def test_parse_output_line_truncated_review_is_error():
    """max_output_tokens truncation yields valid-looking JSON with fields missing."""
    line = _ok_line()
    partial = {k: v for k, v in REVIEW.items() if k != "overall_recommendation"}
    line["response"]["body"]["output"][1]["content"][0]["text"] = json.dumps(partial)
    rec = parse_output_line(line, {PAPER["paper_id"]: PAPER}, MODEL)
    assert rec["status"] == "error"


def test_merge_preserves_records_the_batch_did_not_cover(tmp_path):
    """A fetch must not wipe reviews an earlier sync run appended."""
    out = tmp_path / "reviews.jsonl"
    out.write_text(
        json.dumps({"paper_id": "kept", "status": "ok"}) + "\n"
        + json.dumps({"paper_id": "stale", "status": "error"}) + "\n"
    )
    merged = merge_into_dataset(out, [{"paper_id": "stale", "status": "ok"},
                                      {"paper_id": "fresh", "status": "ok"}])
    by_id = {r["paper_id"]: r for r in merged}
    assert set(by_id) == {"kept", "stale", "fresh"}
    assert by_id["stale"]["status"] == "ok"


def test_merge_never_downgrades_a_successful_review(tmp_path):
    """The documented repair loop is fetch -> sync-rerun failures -> fetch, so a
    second fetch must not overwrite a repaired review with the original error."""
    out = tmp_path / "reviews.jsonl"
    prior = {"paper_id": "kept", "status": "ok",
             "review": {"overall_recommendation": 4}}
    out.write_text(json.dumps(prior) + "\n")
    merged = merge_into_dataset(
        out, [{"paper_id": "kept", "status": "error", "error": "boom"}])
    assert merged == [prior]


def test_merge_into_missing_file_writes_records_only(tmp_path):
    merged = merge_into_dataset(tmp_path / "absent.jsonl", [{"paper_id": "a"}])
    assert merged == [{"paper_id": "a"}]


def test_other_model_states_detects_shared_pdf_owners(tmp_path, monkeypatch):
    """--cleanup deletes PDFs referenced by file_id, which a second in-flight
    batch would share; it must notice one exists."""
    monkeypatch.setattr("openai_review_icml_batch.ROOT", tmp_path)
    (tmp_path / "data").mkdir()
    save_state(MODEL, {"batch_id": "b1"})
    assert other_model_states(MODEL) == []
    save_state("gpt-5.1", {"batch_id": "b2"})
    assert [p.name for p in other_model_states(MODEL)] == [
        "openai_batch_state_gpt-5.1.json"
    ]


def test_state_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr("openai_review_icml_batch.ROOT", tmp_path)
    (tmp_path / "data").mkdir()
    save_state(MODEL, {"batch_id": "batch_xyz", "input_file_id": "file-in", "n": 347})
    assert load_state(MODEL)["batch_id"] == "batch_xyz"
    assert state_path(MODEL).name == f"openai_batch_state_{MODEL}.json"


def test_load_state_missing_returns_none(tmp_path, monkeypatch):
    monkeypatch.setattr("openai_review_icml_batch.ROOT", tmp_path)
    (tmp_path / "data").mkdir()
    assert load_state("gpt-nonexistent") is None


def test_batch_cost_is_half_of_sync():
    assert batch_cost(MODEL, 1_000_000, 1_000_000) == pytest.approx(
        sync_cost(MODEL, 1_000_000, 1_000_000) / 2
    )


class _StubFiles:
    def __init__(self, contents: dict):
        self.contents = contents
        self.deleted = []

    def content(self, file_id):
        return SimpleNamespace(text=self.contents[file_id])

    def delete(self, file_id):
        self.deleted.append(file_id)


class _StubClient:
    def __init__(self, batch, contents):
        self.files = _StubFiles(contents)
        self.batches = SimpleNamespace(retrieve=lambda _id: batch)


def test_cmd_fetch_reads_both_output_and_error_files(tmp_path, monkeypatch, capsys):
    """A batch writes failed requests to a separate error_file; ignoring it
    would silently shrink the dataset below the number of papers submitted."""
    other = dict(PAPER, paper_id="99999999-0000-0000-0000-000000000000")
    err_line = {"custom_id": other["paper_id"],
                "error": {"code": "server_error", "message": "boom"},
                "response": None}

    batch = SimpleNamespace(status="completed", output_file_id="file-out",
                            error_file_id="file-err")
    client = _StubClient(batch, {
        "file-out": json.dumps(_ok_line()) + "\n",
        "file-err": json.dumps(err_line) + "\n",
    })

    out = tmp_path / "reviews.jsonl"
    monkeypatch.setattr("openai_review_icml_batch.ROOT", tmp_path)
    (tmp_path / "data").mkdir()
    monkeypatch.setattr("openai_review_icml_batch._client", lambda: client)
    monkeypatch.setattr("openai_review_icml_batch.out_path", lambda _m: out)
    save_state(MODEL, {"batch_id": "b", "input_file_id": "file-in",
                       "papers": [PAPER, other]})

    cmd_fetch(SimpleNamespace(model=MODEL, cleanup=False))

    written = [json.loads(l) for l in out.read_text().splitlines()]
    by_id = {r["paper_id"]: r for r in written}
    assert by_id[PAPER["paper_id"]]["status"] == "ok"
    assert by_id[other["paper_id"]]["status"] == "error"
    assert "server_error" in by_id[other["paper_id"]]["error"]
    assert "WARNING" not in capsys.readouterr().out


def test_cmd_fetch_warns_when_a_paper_returns_no_record(tmp_path, monkeypatch, capsys):
    missing = dict(PAPER, paper_id="88888888-0000-0000-0000-000000000000",
                   title="Never Came Back")
    batch = SimpleNamespace(status="completed", output_file_id="file-out",
                            error_file_id=None)
    client = _StubClient(batch, {"file-out": json.dumps(_ok_line()) + "\n"})

    monkeypatch.setattr("openai_review_icml_batch.ROOT", tmp_path)
    (tmp_path / "data").mkdir()
    monkeypatch.setattr("openai_review_icml_batch._client", lambda: client)
    monkeypatch.setattr("openai_review_icml_batch.out_path",
                        lambda _m: tmp_path / "reviews.jsonl")
    save_state(MODEL, {"batch_id": "b", "input_file_id": "file-in",
                       "papers": [PAPER, missing]})

    cmd_fetch(SimpleNamespace(model=MODEL, cleanup=False))

    printed = capsys.readouterr().out
    assert "WARNING" in printed
    assert "Never Came Back" in printed


def test_cmd_fetch_refuses_incomplete_batch(tmp_path, monkeypatch):
    batch = SimpleNamespace(status="in_progress", output_file_id=None,
                            error_file_id=None)
    monkeypatch.setattr("openai_review_icml_batch.ROOT", tmp_path)
    (tmp_path / "data").mkdir()
    monkeypatch.setattr("openai_review_icml_batch._client",
                        lambda: _StubClient(batch, {}))
    save_state(MODEL, {"batch_id": "b", "input_file_id": "f", "papers": [PAPER]})

    with pytest.raises(SystemExit):
        cmd_fetch(SimpleNamespace(model=MODEL, cleanup=False))


def test_cmd_fetch_cleanup_deletes_output_and_error_files(tmp_path, monkeypatch):
    """The batch's own output/error files are billed storage too -- deleting
    only the input file leaks them on every run."""
    batch = SimpleNamespace(status="completed", output_file_id="file-out",
                            error_file_id="file-err")
    client = _StubClient(batch, {"file-out": json.dumps(_ok_line()) + "\n",
                                 "file-err": ""})
    monkeypatch.setattr("openai_review_icml_batch.ROOT", tmp_path)
    (tmp_path / "data").mkdir()
    monkeypatch.setattr("openai_review_icml_batch._client", lambda: client)
    monkeypatch.setattr("openai_review_icml_batch.out_path",
                        lambda _m: tmp_path / "reviews.jsonl")
    save_state(MODEL, {"batch_id": "b", "input_file_id": "file-in",
                       "papers": [PAPER]})
    (tmp_path / "data" / "openai_file_ids.json").write_text(
        json.dumps({"uuid-a": "file-pdf-a"}))

    cmd_fetch(SimpleNamespace(model=MODEL, cleanup=True))

    assert set(client.files.deleted) == {"file-pdf-a", "file-in", "file-out", "file-err"}
    assert not state_path(MODEL).exists()
