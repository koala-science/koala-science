import json
import sys
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

import anthropic
import claude_review_icml as sync_mod
from icml_review_prompt import ICML_INSTRUCTIONS, ICMLReview
from claude_review_icml_batch import (
    MAX_TOKENS,
    cmd_fetch,
    batch_cost,
    build_request,
    icml_output_config,
    load_state,
    merge_into_dataset,
    parse_result,
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
MODEL = "claude-sonnet-5"
FILE_ID = "file_abc123"


REVIEW = {
    "summary": "s", "strengths_and_weaknesses": "sw", "soundness": 3,
    "presentation": 3, "significance": 2, "originality": 2,
    "key_questions_for_authors": "q", "limitations": "l",
    "overall_recommendation": 4, "confidence": 3,
}


def test_output_config_is_byte_identical_to_what_the_sdk_sends():
    """The batch endpoint cannot take output_format=ICMLReview (the pydantic
    class is not JSON-serialisable there), so the config is built explicitly.
    This pins it against what beta.messages.parse actually puts on the wire --
    if the SDK changes its transform, this fails instead of silently drifting."""
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json={
            "id": "m", "type": "message", "role": "assistant", "model": MODEL,
            "content": [{"type": "text", "text": json.dumps(REVIEW)}],
            "stop_reason": "end_turn", "stop_sequence": None,
            "usage": {"input_tokens": 1, "output_tokens": 1}})

    client = anthropic.Anthropic(
        api_key="x", http_client=httpx.Client(transport=httpx.MockTransport(handler)))
    client.beta.messages.parse(
        model=MODEL, max_tokens=MAX_TOKENS, system=ICML_INSTRUCTIONS,
        output_format=ICMLReview, messages=[{"role": "user", "content": "x"}])

    assert "body" in captured
    assert icml_output_config() == captured["body"]["output_config"]


def test_output_config_shape():
    fmt = icml_output_config()["format"]
    assert fmt["type"] == "json_schema"
    assert fmt["schema"]["additionalProperties"] is False
    assert set(fmt["schema"]["required"]) == set(ICMLReview.model_fields)


def test_build_request_envelope():
    req = build_request(PAPER, MODEL, FILE_ID)
    assert req["custom_id"] == PAPER["paper_id"]
    assert set(req) == {"custom_id", "params"}


def test_build_request_matches_sync_call_params():
    """Parity with claude_review_icml.review_one -- a baseline that differs in
    prompt or content shape measures the harness, not the model."""
    p = build_request(PAPER, MODEL, FILE_ID)["params"]
    assert p["model"] == MODEL
    assert p["system"] == ICML_INSTRUCTIONS
    assert "tools" not in p
    assert "thinking" not in p

    doc, text = p["messages"][0]["content"]
    assert doc == {"type": "document",
                   "source": {"type": "file", "file_id": FILE_ID}}
    assert text == {"type": "text",
                    "text": f"Title: {PAPER['title']}\n\nAbstract: {PAPER['abstract']}"}


def test_build_request_uses_the_same_max_tokens_as_the_sync_script():
    """Sonnet 5's median review is 5851 output tokens and 48 of 345 exceeded
    the original 8192, so both paths were raised. They must stay equal: batch
    failures are repaired by re-running them through the sync script, and a
    tighter cap there would truncate exactly the responses that already
    overflowed. The ceiling is the SDK's 21333 non-streaming limit, which the
    sync path hits first."""
    assert MAX_TOKENS == sync_mod.MAX_TOKENS
    assert build_request(PAPER, MODEL, FILE_ID)["params"]["max_tokens"] == MAX_TOKENS


def test_build_request_is_json_serialisable():
    """output_format=ICMLReview cannot be sent here -- it raises
    'ModelMetaclass is not JSON serializable' inside batches.create."""
    json.dumps(build_request(PAPER, MODEL, FILE_ID))


def _succeeded(text=None, usage=(60000, 4000)):
    return SimpleNamespace(
        type="succeeded",
        message=SimpleNamespace(
            content=[SimpleNamespace(type="text",
                                     text=json.dumps(REVIEW) if text is None else text)],
            usage=SimpleNamespace(input_tokens=usage[0], output_tokens=usage[1]),
            stop_reason="end_turn"))


def test_parse_result_ok():
    rec = parse_result(PAPER["paper_id"], _succeeded(), {PAPER["paper_id"]: PAPER}, MODEL)
    assert rec["status"] == "ok"
    assert rec["review"] == REVIEW
    assert rec["usage"] == {"input": 60000, "output": 4000}
    assert rec["model"] == MODEL


def test_parse_result_record_shape_matches_sync_dataset():
    """load_ai_scores reads these files; keys must match the shipped datasets."""
    rec = parse_result(PAPER["paper_id"], _succeeded(), {PAPER["paper_id"]: PAPER}, MODEL)
    assert set(rec) == {
        "paper_id", "forum_id", "title", "model", "status", "review", "usage"}
    ICMLReview.model_validate(rec["review"])


def test_parse_result_skips_thinking_blocks():
    """Sonnet 5 returns thinking blocks ahead of the text block."""
    r = _succeeded()
    r.message.content.insert(0, SimpleNamespace(type="thinking", thinking=""))
    assert parse_result(PAPER["paper_id"], r, {PAPER["paper_id"]: PAPER},
                        MODEL)["status"] == "ok"


def _errored(kind="invalid_request_error", message="file_abc not found"):
    """Built from the real SDK model: the wire nests the actual error one level
    deeper than result.error, and a hand-rolled stub that flattens it would
    certify a parser that reports the constant string 'error'."""
    from anthropic.types.beta.messages import BetaMessageBatchIndividualResponse

    return BetaMessageBatchIndividualResponse.model_validate({
        "custom_id": PAPER["paper_id"],
        "result": {"type": "errored", "error": {
            "type": "error", "error": {"type": kind, "message": message}}},
    }).result


def test_parse_result_errored_keeps_the_real_error_detail():
    rec = parse_result(PAPER["paper_id"], _errored(), {PAPER["paper_id"]: PAPER}, MODEL)
    assert rec["status"] == "error"
    assert "invalid_request_error" in rec["error"]
    assert "file_abc not found" in rec["error"]


@pytest.mark.parametrize("kind", ["canceled", "expired"])
def test_parse_result_canceled_and_expired(kind):
    rec = parse_result(PAPER["paper_id"], SimpleNamespace(type=kind),
                       {PAPER["paper_id"]: PAPER}, MODEL)
    assert rec["status"] == "error"
    assert kind in rec["error"]


def test_parse_result_missing_field_is_error():
    """A response that parses as JSON but omits a required field."""
    partial = {k: v for k, v in REVIEW.items() if k != "overall_recommendation"}
    rec = parse_result(PAPER["paper_id"], _succeeded(text=json.dumps(partial)),
                       {PAPER["paper_id"]: PAPER}, MODEL)
    assert rec["status"] == "error"


def test_parse_result_truncated_at_the_cap_is_error_even_when_the_json_parses():
    """A max_tokens stop can still emit complete, valid JSON -- one sonnet-5
    paper did, with two required text fields left empty. Only the stop reason
    distinguishes it from a real review."""
    result = _succeeded(usage=(60000, MAX_TOKENS))
    result.message.stop_reason = "max_tokens"
    rec = parse_result(PAPER["paper_id"], result, {PAPER["paper_id"]: PAPER}, MODEL)
    assert rec["status"] == "error"
    assert "truncated at the token cap" in rec["error"]


def test_parse_result_unparseable_is_error():
    rec = parse_result(PAPER["paper_id"], _succeeded(text="not json{"),
                       {PAPER["paper_id"]: PAPER}, MODEL)
    assert rec["status"] == "error"


def test_merge_never_downgrades_a_successful_review(tmp_path):
    out = tmp_path / "r.jsonl"
    prior = {"paper_id": "kept", "status": "ok", "review": {"overall_recommendation": 4}}
    out.write_text(json.dumps(prior) + "\n")
    merged = merge_into_dataset(out, [{"paper_id": "kept", "status": "error",
                                       "error": "boom"}])
    assert merged == [prior]


def test_merge_supersedes_with_a_fresh_success(tmp_path):
    out = tmp_path / "r.jsonl"
    out.write_text(json.dumps({"paper_id": "p", "status": "error"}) + "\n")
    merged = merge_into_dataset(out, [{"paper_id": "p", "status": "ok"}])
    assert merged[0]["status"] == "ok"


def test_batch_cost_is_half_of_sync():
    assert batch_cost(MODEL, 1_000_000, 1_000_000) == pytest.approx(
        sync_cost(MODEL, 1_000_000, 1_000_000) / 2)


def test_sync_cost_uses_the_shared_pricing_table():
    price = sync_mod.PRICING[MODEL]
    assert sync_cost(MODEL, 1_000_000, 0) == pytest.approx(price["input"])
    assert sync_cost(MODEL, 0, 1_000_000) == pytest.approx(price["output"])


def test_state_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr("claude_review_icml_batch.ROOT", tmp_path)
    (tmp_path / "data").mkdir()
    save_state(MODEL, {"batch_id": "batch_xyz", "papers": [PAPER]})
    assert load_state(MODEL)["batch_id"] == "batch_xyz"
    assert state_path(MODEL).name == f"anthropic_batch_state_{MODEL}.json"


def test_load_state_missing_returns_none(tmp_path, monkeypatch):
    monkeypatch.setattr("claude_review_icml_batch.ROOT", tmp_path)
    (tmp_path / "data").mkdir()
    assert load_state("claude-nonexistent") is None


def test_out_path_is_the_shipped_dataset_filename():
    """load_ai_scores reads these by name; the batch path must not invent one."""
    from claude_review_icml_batch import out_path

    assert out_path(MODEL).name == f"icml_2026_claude_icml_reviews_{MODEL}.jsonl"


class _StubClient:
    """Mirrors the surface cmd_fetch touches: batches.retrieve/results and
    beta.files.delete."""

    def __init__(self, batch, results):
        self.deleted = []
        self.beta = SimpleNamespace(
            files=SimpleNamespace(delete=lambda fid, betas=None: self.deleted.append(fid)),
            messages=SimpleNamespace(batches=SimpleNamespace(
                retrieve=lambda _id, betas=None: batch,
                results=lambda _id, betas=None: iter(results))))


def _fetch_env(tmp_path, monkeypatch, batch, results, papers):
    monkeypatch.setattr("claude_review_icml_batch.ROOT", tmp_path)
    (tmp_path / "data").mkdir(exist_ok=True)
    client = _StubClient(batch, results)
    monkeypatch.setattr("claude_review_icml_batch._client", lambda: client)
    monkeypatch.setattr("claude_review_icml_batch.out_path",
                        lambda _m: tmp_path / "reviews.jsonl")
    save_state(MODEL, {"batch_id": "b", "papers": papers})
    return client


def _ended(status="ended"):
    return SimpleNamespace(id="b", processing_status=status,
                           request_counts=SimpleNamespace(
                               succeeded=1, processing=0, errored=0,
                               canceled=0, expired=0))


def test_cmd_fetch_refuses_a_batch_that_has_not_ended(tmp_path, monkeypatch):
    _fetch_env(tmp_path, monkeypatch, _ended("in_progress"), [], [PAPER])
    with pytest.raises(SystemExit):
        cmd_fetch(SimpleNamespace(model=MODEL, cleanup=False))


def test_cmd_fetch_writes_mixed_success_and_failure(tmp_path, monkeypatch):
    other = dict(PAPER, paper_id="99999999-0000-0000-0000-000000000000")
    results = [
        SimpleNamespace(custom_id=PAPER["paper_id"], result=_succeeded()),
        SimpleNamespace(custom_id=other["paper_id"], result=_errored()),
    ]
    _fetch_env(tmp_path, monkeypatch, _ended(), results, [PAPER, other])
    cmd_fetch(SimpleNamespace(model=MODEL, cleanup=False))

    by_id = {json.loads(l)["paper_id"]: json.loads(l)
             for l in (tmp_path / "reviews.jsonl").read_text().splitlines()}
    assert by_id[PAPER["paper_id"]]["status"] == "ok"
    assert by_id[other["paper_id"]]["status"] == "error"
    assert "file_abc not found" in by_id[other["paper_id"]]["error"]


def test_cmd_fetch_warns_when_a_paper_returns_no_result(tmp_path, monkeypatch, capsys):
    missing = dict(PAPER, paper_id="88888888-0000-0000-0000-000000000000",
                   title="Never Came Back")
    results = [SimpleNamespace(custom_id=PAPER["paper_id"], result=_succeeded())]
    _fetch_env(tmp_path, monkeypatch, _ended(), results, [PAPER, missing])
    cmd_fetch(SimpleNamespace(model=MODEL, cleanup=False))

    printed = capsys.readouterr().out
    assert "WARNING" in printed
    assert "Never Came Back" in printed


def test_cmd_fetch_cleanup_deletes_pdfs_and_state(tmp_path, monkeypatch):
    results = [SimpleNamespace(custom_id=PAPER["paper_id"], result=_succeeded())]
    client = _fetch_env(tmp_path, monkeypatch, _ended(), results, [PAPER])
    (tmp_path / "data" / "anthropic_file_ids.json").write_text(
        json.dumps({"uuid-a": "file_pdf_a", "uuid-b": "file_pdf_b"}))

    cmd_fetch(SimpleNamespace(model=MODEL, cleanup=True))

    assert set(client.deleted) == {"file_pdf_a", "file_pdf_b"}
    assert not state_path(MODEL).exists()


def test_cmd_fetch_cleanup_keeps_pdfs_shared_with_another_model(tmp_path, monkeypatch):
    """PDFs are keyed by pdf_uuid, not model -- deleting them while a second
    model's batch is still in flight kills that batch with dead file_ids."""
    results = [SimpleNamespace(custom_id=PAPER["paper_id"], result=_succeeded())]
    client = _fetch_env(tmp_path, monkeypatch, _ended(), results, [PAPER])
    (tmp_path / "data" / "anthropic_file_ids.json").write_text(
        json.dumps({"uuid-a": "file_pdf_a"}))
    save_state("claude-haiku-4-5", {"batch_id": "other", "papers": []})

    cmd_fetch(SimpleNamespace(model=MODEL, cleanup=True))

    assert client.deleted == []
    assert json.loads((tmp_path / "data" / "anthropic_file_ids.json").read_text())
    assert not state_path(MODEL).exists()
