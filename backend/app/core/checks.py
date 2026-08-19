"""The checks an argument must pass, and the active version of each.

Checks are code, so their versions belong in a diff rather than a table.
Adding one means adding an entry here and its function in ``check_runner``.
"""

CHECKS: dict[str, str] = {}
