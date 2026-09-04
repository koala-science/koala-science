"""Serialising arguments with each check's flag count filled in.

The count is not a column or a relationship on ``ArgumentCheck``: reading it off
the ORM costs a lazy load per check, and a freshly created argument has no
loaded collection to read. One grouped query per response serves any number of
arguments, and every endpoint that publishes check results uses this so none of
them can quietly report zero.
"""
from collections.abc import Sequence

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.platform import Argument, ArgumentCheck, CheckFlag
from app.schemas.platform import ArgumentResponse


async def arguments_with_flag_counts(
    db: AsyncSession, arguments: Sequence[Argument]
) -> list[ArgumentResponse]:
    # Filtered on the arguments rather than their checks: an export page holds
    # up to 10 000 arguments and each carries a row per check, which is more
    # bind parameters than the driver accepts.
    counts = dict(
        (
            await db.execute(
                select(CheckFlag.check_id, func.count(CheckFlag.id))
                .join(ArgumentCheck, ArgumentCheck.id == CheckFlag.check_id)
                .where(ArgumentCheck.argument_id.in_([a.id for a in arguments]))
                .group_by(CheckFlag.check_id)
            )
        ).all()
    )

    responses = [ArgumentResponse.model_validate(a) for a in arguments]
    for response in responses:
        for check in response.checks:
            check.flag_count = counts.get(check.id, 0)
    return responses
