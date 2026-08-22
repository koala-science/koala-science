"""Institutional-address policy for signup.

A signing-up human claims an OpenReview ID. OpenReview will tell us the
**domains** on that profile and nothing finer — the local part of every address
is masked. Comparing domains is therefore the only cross-check available, and it
is worth something only because free webmail is refused: a profile listing
``****@gmail.com`` would otherwise admit anyone who owns a Gmail account.

What the pair of checks establishes: the person holds a mailbox at an institution
their claimed profile lists. A colleague at the same institution could still
claim a coworker's profile; closing that needs a proof only the profile owner can
produce, which was judged too much friction for the platform.
"""

FREE_EMAIL_DOMAINS = frozenset({
    "gmail.com", "googlemail.com",
    "outlook.com", "hotmail.com", "hotmail.co.uk", "live.com", "msn.com",
    "yahoo.com", "yahoo.co.uk", "yahoo.co.jp", "ymail.com",
    "proton.me", "protonmail.com", "pm.me",
    "icloud.com", "me.com", "mac.com",
    "aol.com", "gmx.com", "gmx.de", "gmx.net",
    "yandex.ru", "yandex.com", "mail.ru",
    "qq.com", "163.com", "126.com", "sina.com", "foxmail.com",
    "zoho.com", "fastmail.com", "hey.com",
    "tutanota.com", "tuta.io", "duck.com",
    "hotmail.fr", "outlook.fr", "web.de", "free.fr", "libero.it",
})


def domain_of(email: str) -> str:
    """The domain part, lowercased."""
    _, _, domain = email.strip().rpartition("@")
    return domain.lower()


def is_free_email(domain: str) -> bool:
    return domain.strip().lower() in FREE_EMAIL_DOMAINS


# Suffixes under which anyone may register, so "the signup domain is a parent of
# a domain on the profile" must not reach them: `edu` is a parent of
# `stanford.edu`, and treating that as a match would admit an entire namespace.
PUBLIC_SUFFIXES = frozenset({
    "com", "org", "net", "edu", "gov", "int", "mil", "info", "biz", "io", "ai",
    "co", "ac", "ac.uk", "co.uk", "org.uk", "gov.uk", "ac.jp", "co.jp",
    "edu.au", "com.au", "org.au", "edu.cn", "com.cn", "ac.cn", "edu.sg",
    "ac.in", "edu.in", "edu.br", "com.br", "ac.za", "ac.kr", "edu.hk",
    "ac.nz", "edu.mx", "edu.tr", "ac.il", "edu.pl", "ac.be", "ac.at",
})


def _is_registrable(domain: str) -> bool:
    """Whether a domain is specific enough to stand for one institution."""
    return domain.count(".") >= 1 and domain not in PUBLIC_SUFFIXES


def _is_same_or_subdomain(signup: str, profile: str) -> bool:
    """True when the domains are equal, or one sits under the other.

    Matching on the dotted boundary rather than a bare suffix is what keeps
    ``evilstanford.edu`` and ``stanford.edu.evil.com`` from passing as Stanford.

    The parent direction — a profile listing ``cs.stanford.edu`` while someone
    signs up at ``stanford.edu`` — is allowed, but only up to a registrable
    domain. Without that floor, ``edu`` would match ``stanford.edu`` and one
    signup domain would stand for every institution beneath it.
    """
    if signup == profile:
        return True
    if signup.endswith(f".{profile}"):
        return _is_registrable(profile)
    return profile.endswith(f".{signup}") and _is_registrable(signup)


def domains_match(signup_domain: str, profile_domains) -> bool:
    """Whether the signup domain is one this profile lists.

    Free-webmail domains on either side are skipped: they carry no institutional
    meaning, and honouring them would make the check meaningless.
    """
    signup = signup_domain.strip().lower()
    if is_free_email(signup):
        return False

    return any(
        _is_same_or_subdomain(signup, candidate.strip().lower())
        for candidate in profile_domains
        if not is_free_email(candidate)
    )
