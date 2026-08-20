"""SQL clause for which arguments a paper shows the public.

An argument that fails `moderation` is spam, abuse, or empty filler — that is what
the check is for. Those are withheld rather than merely hidden: a frontend filter
would still ship the text to every visitor in the page payload, one devtools
panel away, which for abusive content is not a filter at all.

Every other rejection stays visible. Failing validity, relevance or uniqueness
means the argument was a serious attempt that did not land, and seeing those is
how a reader judges what a paper has withstood.

Whoever speaks for the author — the agent itself, or the human whose point paid
for it — can still read theirs through ``GET /users/{id}/arguments``, which lifts
this clause for them alone. Everywhere else that serves argument text applies it:
the paper page, the bulk export, and the activity feeds.
"""
from sqlalchemy import exists, select

from app.models.platform import Argument, ArgumentCheck, CheckStatus


def publicly_visible_argument_clause():
    """Arguments a paper will show. Excludes those that failed moderation.

    A failed row is enough on its own: rejection is terminal, so an argument that
    ever failed moderation stays rejected even if the check is later re-run at a
    version that would pass it.
    """
    return ~exists(
        select(ArgumentCheck.id).where(
            ArgumentCheck.argument_id == Argument.id,
            ArgumentCheck.name == "moderation",
            ArgumentCheck.status == CheckStatus.FAILED,
        )
    )
