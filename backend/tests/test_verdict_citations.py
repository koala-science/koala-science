"""Unit tests for the ``[[comment:<uuid>]]`` citation parser."""
import uuid

from app.core.verdict_citations import extract_citation_ids


def test_no_citations_returns_empty_list():
    assert extract_citation_ids("This verdict has no citations at all.") == []


def test_single_citation():
    cid = uuid.uuid4()
    markdown = f"I agree with [[comment:{cid}]] on this point."
    assert extract_citation_ids(markdown) == [cid]


def test_multiple_unique_citations_preserve_order():
    a, b, c = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    markdown = (
        f"Strongest arguments come from [[comment:{a}]], [[comment:{b}]], "
        f"and [[comment:{c}]]."
    )
    assert extract_citation_ids(markdown) == [a, b, c]


def test_duplicates_collapse_to_single_entry():
    cid = uuid.uuid4()
    markdown = (
        f"Repeating myself: [[comment:{cid}]] says X, and [[comment:{cid}]] "
        f"repeats it."
    )
    assert extract_citation_ids(markdown) == [cid]


def test_duplicates_only_count_once_even_across_many_repeats():
    a, b = uuid.uuid4(), uuid.uuid4()
    markdown = (
        f"[[comment:{a}]] [[comment:{b}]] [[comment:{a}]] [[comment:{b}]] "
        f"[[comment:{a}]]"
    )
    assert extract_citation_ids(markdown) == [a, b]


def test_mixed_case_uuids_are_normalized_and_deduped():
    cid = uuid.uuid4()
    upper = str(cid).upper()
    markdown = f"[[comment:{cid}]] and [[COMMENT:{upper}]]"
    assert extract_citation_ids(markdown) == [cid]


def test_tokens_inside_code_blocks_still_parse():
    """Parser is not markdown-aware — that's a known, documented caveat."""
    cid = uuid.uuid4()
    markdown = f"```\n[[comment:{cid}]]\n```"
    assert extract_citation_ids(markdown) == [cid]


def test_malformed_token_is_ignored():
    markdown = "[[comment:not-a-uuid]] and [[comment:123]]"
    assert extract_citation_ids(markdown) == []


def test_returns_uuid_objects_not_strings():
    cid = uuid.uuid4()
    result = extract_citation_ids(f"[[comment:{cid}]]")
    assert len(result) == 1
    assert isinstance(result[0], uuid.UUID)
