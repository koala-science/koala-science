"""Which addresses count as institutional, and when a domain matches a profile.

The whole strength of the signup check rests here. A profile's emails are masked
to `****@domain`, so the domain is all we can compare — which is worth something
only if free webmail is refused. `****@gmail.com` on a profile would otherwise
admit anyone with a Gmail account.
"""
import pytest

from app.core.email_domains import domain_of, domains_match, is_free_email


@pytest.mark.parametrize("domain", [
    "gmail.com", "GMail.com", "googlemail.com", "outlook.com", "hotmail.com",
    "yahoo.com", "proton.me", "protonmail.com", "icloud.com", "qq.com",
    "163.com", "yandex.ru", "mail.ru", "gmx.de", "aol.com", "fastmail.com",
])
def test_free_providers_are_refused(domain):
    assert is_free_email(domain) is True


@pytest.mark.parametrize("domain", [
    "mila.quebec", "mcgill.ca", "stanford.edu", "cs.stanford.edu", "ox.ac.uk",
    "uc.cl", "ethz.ch", "tsinghua.edu.cn", "deepmind.com",
])
def test_institutional_domains_are_allowed(domain):
    assert is_free_email(domain) is False


def test_domain_of_lowercases_and_strips():
    assert domain_of("Alice@Mila.Quebec") == "mila.quebec"


@pytest.mark.parametrize("signup,profile", [
    ("mila.quebec", "mila.quebec"),
    ("cs.stanford.edu", "stanford.edu"),
    ("stanford.edu", "cs.stanford.edu"),
    ("eecs.mit.edu", "mit.edu"),
])
def test_matching_accepts_exact_and_either_direction_of_subdomain(signup, profile):
    assert domains_match(signup, [profile]) is True


@pytest.mark.parametrize("signup,profile", [
    ("mila.quebec", "mcgill.ca"),
    ("notstanford.edu", "stanford.edu"),
    ("stanford.edu.evil.com", "stanford.edu"),
    ("evilstanford.edu", "stanford.edu"),
])
def test_matching_refuses_unrelated_and_lookalike_domains(signup, profile):
    assert domains_match(signup, [profile]) is False


def test_matching_ignores_free_domains_on_the_profile():
    """A gmail on the profile must not admit a gmail signup through this path."""
    assert domains_match("gmail.com", ["gmail.com", "mila.quebec"]) is False


def test_matching_scans_every_profile_domain():
    assert domains_match("uc.cl", ["gmail.com", "mila.quebec", "uc.cl"]) is True


@pytest.mark.parametrize("signup,profile", [
    ("edu", "stanford.edu"),
    ("ac.uk", "ox.ac.uk"),
    ("com", "deepmind.com"),
    ("quebec", "mila.quebec"),
])
def test_a_parent_domain_cannot_stand_for_everything_beneath_it(signup, profile):
    """`edu` matching `stanford.edu` would make one signup domain mean every
    institution under it."""
    assert domains_match(signup, [profile]) is False


def test_a_registrable_parent_still_matches():
    """The case the parent direction exists for: the profile is more specific."""
    assert domains_match("stanford.edu", ["cs.stanford.edu"]) is True


def test_neither_direction_reaches_a_public_suffix():
    """Symmetric with the parent case: a bare suffix must not stand for a domain."""
    assert domains_match("evil.edu", ["edu"]) is False
    assert domains_match("evil.ac.uk", ["ac.uk"]) is False
