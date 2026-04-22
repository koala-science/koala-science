import pytest

from app.schemas.auth import GITHUB_REPO_PATTERN


@pytest.mark.parametrize(
    "url",
    [
        "https://github.com/owner/repo",
        "https://github.com/owner/repo/",
        "https://github.com/owner/repo.git",
        "https://github.com/owner-name/repo-name",
        "https://github.com/owner_name/repo.name",
        "https://github.com/anthropics/sleeper-agents-paper",
        "http://github.com/foo/bar",
    ],
)
def test_valid_urls(url: str) -> None:
    assert GITHUB_REPO_PATTERN.match(url) is not None


@pytest.mark.parametrize(
    "url",
    [
        "",
        "github.com/owner/repo",
        "https://gitlab.com/owner/repo",
        "https://github.com/owner",
        "https://github.com/owner/",
        "https://github.com/owner/repo/blob/main/file.md",
        "https://github.com/owner/repo with spaces",
        "not a url",
    ],
)
def test_invalid_urls(url: str) -> None:
    assert GITHUB_REPO_PATTERN.match(url) is None
