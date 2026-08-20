"""The checks an argument must pass, and the active version of each.

Checks are code, so their versions belong in a diff rather than a table.
Adding one means adding an entry here and its function in ``check_runner``.

**Order matters.** Checks run in sequence and a failure ends the sequence, so
the cheapest and coarsest gate belongs first: an argument that is spam is never
assessed for whether its claim is atomic.
"""

CHECKS: dict[str, str] = {
    # Is this a serious contribution at all: register, substance, targeting.
    "moderation": "v1",
    # Is it shaped like an argument: atomic claim, related and checkable evidence.
    "validity": "v1",
    # Has it already been made about this paper by someone else.
    "uniqueness": "v1",
}


def first_check() -> tuple[str, str] | None:
    """The check an argument enters the pipeline at, or None if none are configured.

    Every path that creates an argument has to queue this one, and only this
    one — each check queues its successor when it passes.
    """
    return next(iter(CHECKS.items()), None)
