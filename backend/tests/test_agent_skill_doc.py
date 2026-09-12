"""The agent onboarding doc has to describe the API agents actually meet.

`frontend/public/skill.md` is what an agent author reads to get onto the
platform, and nothing checked it against the code. It drifted: self-serve
verification started returning the token in the signup response, and the doc
went on saying the response "contains no token" and to wait for a mail that a
deployment without a sender never sends — stranding the very people the change
was meant to unblock.

The lesson from fixing it badly the first time: prose cannot be guarded by
matching prose. Every phrasing rule admits a rephrasing that says the opposite,
and rejects some correct sentence. So the doc states its claim as a truth
table, and this module **runs** that table — each documented row is exercised
against the real endpoint and the real sender, and a row the platform does not
honour fails.

The prose around the table is kept deliberately thin, because prose beside a
normative table can still contradict it and no assertion here can catch every
way of doing that. What is caught is the small set of claims that have actually
gone wrong: that the token is always null, and that self-serve is what stops
the mail.
"""
import re
import uuid
from pathlib import Path

import pytest

from app.core.config import settings
from app.schemas.auth import SignupResponse

SKILL_DOC = Path(__file__).resolve().parents[2] / "frontend" / "public" / "skill.md"
SKILL_TEXT = SKILL_DOC.read_text()


def _signup_section() -> str:
    """The doc down to the heading after registration.

    Fails naming itself rather than the document it inspects: a renamed heading
    is this test's problem to notice, not evidence that skill.md is wrong.
    """
    marker = "## Authenticate"
    index = SKILL_TEXT.find(marker)
    assert index != -1, (
        f"no {marker!r} heading in {SKILL_DOC} — has it been renamed? "
        "this test slices the registration section at it"
    )
    return SKILL_TEXT[:index]


SIGNUP = _signup_section()


# The columns this module knows how to run, in the order it reads them. Parsed
# rather than assumed: the rows carry no labels, so a reordered or relabelled
# header would silently turn "mail sender" into something else and the values
# would still line up.
EXPECTED_COLUMNS = ("self-serve", "mail sender", "verification_token", "link mailed")


def _documented_rows() -> list[tuple[bool, bool, bool, bool]]:
    """The signup truth table, as (self_serve, has_sender, token, mailed)."""
    header = re.search(r"^\s*\|(.+verification_token.+)\|\s*$", SIGNUP, re.MULTILINE)
    assert header, (
        f"no signup truth-table header in {SKILL_DOC} — has the table been "
        "reformatted or removed?"
    )
    cells = [c.strip().strip("`").lower() for c in header.group(1).split("|")]
    assert len(cells) == len(EXPECTED_COLUMNS), (
        f"signup truth table has {len(cells)} columns, this test runs "
        f"{len(EXPECTED_COLUMNS)}: {cells}"
    )
    for position, (cell, expected) in enumerate(zip(cells, EXPECTED_COLUMNS), 1):
        assert expected in cell, (
            f"column {position} of the signup truth table reads "
            f"{cell!r}; this test runs it as {expected!r}. Reordering or "
            "relabelling the columns changes what the rows mean."
        )

    rows = re.findall(
        r"^\s*\|\s*(on|off)\s*\|\s*(yes|no)\s*\|\s*(token|null)\s*\|\s*(yes|no)\s*\|\s*$",
        SIGNUP,
        re.MULTILINE,
    )
    assert len(rows) == 4, (
        f"expected 4 rows in the signup truth table in {SKILL_DOC}, found "
        f"{len(rows)} — has the table been reformatted or removed?"
    )
    return [(a == "on", b == "yes", c == "token", d == "yes") for a, b, c, d in rows]


DOCUMENTED_ROWS = _documented_rows()


def test_the_documented_response_has_exactly_the_fields_the_schema_returns():
    """Parsed, not searched for.

    Looking for bare field names anywhere in the document passed on a doc that
    mentioned `verification_token` only to say it is always null — and `email`
    matches forty unrelated lines.
    """
    match = re.search(r"`201 (\{[^`]*\})`", SIGNUP)
    assert match, (
        f"no documented `201 {{...}}` signup response literal in {SKILL_DOC}; "
        "has the registration section been reformatted?"
    )
    documented = set(re.findall(r'"([a-z_]+)":', match.group(1)))
    assert documented == set(SignupResponse.model_fields)


def test_the_table_covers_every_combination():
    """Four rows, one per combination — not four restatements of one case."""
    assert {(row[0], row[1]) for row in DOCUMENTED_ROWS} == {
        (True, True), (True, False), (False, True), (False, False)
    }


@pytest.mark.parametrize(
    "self_serve,has_sender,token_documented,mail_documented", DOCUMENTED_ROWS
)
async def test_each_documented_row_is_what_the_platform_does(
    client, monkeypatch, self_serve, has_sender, token_documented, mail_documented
):
    """Run the row rather than read it.

    One signup answers both columns: the response carries the token or it does
    not, and the mail either reached the network or it did not. Measuring the
    mail by calling `send_email` separately proved worthless — deleting the
    `add_task` that mails the link left every row passing.

    The recorder is installed BEFORE the signup on purpose. `_deliver` runs as a
    background task inside this request, so a recorder installed afterwards
    misses it entirely — and with a key configured, the first version of this
    test sent live requests to api.resend.com, swallowed by `_deliver`'s own
    error handling.
    """
    import app.core.email as email_module

    reached_network: list[str] = []

    class _StubResponse:
        status_code = 200
        text = "{}"

    class _Recorder:
        def __init__(self, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def post(self, url, **kwargs):
            if url == email_module.RESEND_API_URL:
                reached_network.append(url)
            return _StubResponse()

    monkeypatch.setattr(email_module.httpx, "AsyncClient", _Recorder)
    monkeypatch.setattr(settings, "SELF_SERVE_VERIFICATION", self_serve)
    monkeypatch.setattr(settings, "RESEND_API_KEY", "re_test_key" if has_sender else "")

    resp = await client.post(
        "/api/v1/auth/signup",
        json={
            "email": f"table_{uuid.uuid4().hex[:10]}@example.com",
            "openreview_id": f"~Table_Row_{uuid.uuid4().hex[:8]}1",
        },
    )
    assert resp.status_code == 201, resp.text

    token_returned = resp.json()["verification_token"] is not None
    assert token_returned == token_documented, (
        f"skill.md says verification_token is "
        f"{'the token' if token_documented else 'null'} when self-serve is "
        f"{'on' if self_serve else 'off'}, but signup returned "
        f"{'a token' if token_returned else 'null'}"
    )

    assert bool(reached_network) == mail_documented, (
        f"skill.md says a link is {'' if mail_documented else 'not '}mailed when a "
        f"sender is {'configured' if has_sender else 'not configured'}, but signup "
        f"{'sent one' if reached_network else 'sent nothing'}"
    )


# Claims that were true before self-serve verification existed, or that state
# the coupling the table exists to deny. Narrow on purpose: the discriminator
# for the second is the CONDITIONAL — "no mail ... when self-serve" asserts the
# coupling, while "self-serve has no bearing on whether mail is sent" denies it,
# and a rule that cannot tell those apart is worse than no rule.
ALWAYS_NULL = re.compile(r"always\s+`?null`?", re.IGNORECASE)
MAIL_COUPLED_TO_SELF_SERVE = (
    re.compile(
        r"\b(?:no|never|nothing)\b[^.]*mail[^.]*\b(?:when|if|under|with)\b[^.]*self.serve",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:when|if|under|with)\b[^.]*self.serve[^.]*\b(?:no|never|nothing)\b[^.]*mail",
        re.IGNORECASE,
    ),
)


def test_the_prose_does_not_call_the_token_always_null():
    match = ALWAYS_NULL.search(SIGNUP)
    assert not match, (
        f"skill.md says {match.group(0)!r} of verification_token; it is null only "
        "when self-serve verification is off, as the table states"
    )


def test_the_prose_does_not_blame_self_serve_for_the_missing_mail():
    """Whether mail is sent depends on the sender, never on this flag."""
    for pattern in MAIL_COUPLED_TO_SELF_SERVE:
        match = pattern.search(SIGNUP)
        assert not match, (
            f"skill.md ties the absent mail to self-serve in {match.group(0)!r}; "
            "the sender is what decides, and the table says so"
        )
