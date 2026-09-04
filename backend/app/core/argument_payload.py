"""Building the public payload for a page of arguments.

Two of its fields cannot live on the ORM object. ``flag_count`` would be a lazy
load per check, and ``author_response`` a lazy load per argument — and both would
fire on the argument-creation path, where the objects were just constructed in
Python and no collection is loaded. Reading them here instead costs two queries
per page however many arguments it holds, and keeps every endpoint that publishes
arguments serving the same shape.
"""
from collections.abc import Sequence

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.identity import Actor
from app.models.platform import Argument, ArgumentCheck, AuthorResponse, CheckFlag
from app.schemas.platform import ArgumentResponse, AuthorResponseRead


async def public_arguments(
    db: AsyncSession, arguments: Sequence[Argument]
) -> list[ArgumentResponse]:
    argument_ids = [argument.id for argument in arguments]

    # Filtered on the arguments rather than their checks: an export page holds
    # up to 10 000 arguments and each carries a row per check, which is more
    # bind parameters than the driver accepts.
    flag_counts = dict(
        (
            await db.execute(
                select(CheckFlag.check_id, func.count(CheckFlag.id))
                .join(ArgumentCheck, ArgumentCheck.id == CheckFlag.check_id)
                .where(ArgumentCheck.argument_id.in_(argument_ids))
                .group_by(CheckFlag.check_id)
            )
        ).all()
    )

    responses = {
        response.argument_id: AuthorResponseRead(
            id=response.id,
            argument_id=response.argument_id,
            author_id=response.author_id,
            author_name=author_name,
            body=response.body,
            created_at=response.created_at,
        )
        for response, author_name in (
            await db.execute(
                select(AuthorResponse, Actor.name)
                .join(Actor, Actor.id == AuthorResponse.author_id)
                .where(AuthorResponse.argument_id.in_(argument_ids))
            )
        ).all()
    }

    payloads = [ArgumentResponse.model_validate(a) for a in arguments]
    for payload in payloads:
        for check in payload.checks:
            check.flag_count = flag_counts.get(check.id, 0)
        payload.author_response = responses.get(payload.id)
    return payloads
