"""
Drains the queue for the agentic checks.

Run continuously:   python -m scripts.run_verification
Run one pass:       python -m scripts.run_verification --once

Separate from ``run_checks`` because a verification run takes minutes and
``run_pending_checks`` works through its batch one at a time: sharing a worker
would put every argument's moderation behind someone else's agent.
"""
import argparse
import asyncio
import logging

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.check_runner import AGENTIC_CHECKS, run_pending_checks
from app.core.config import settings

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("run_verification")


async def main(once: bool, interval: float) -> None:
    if not settings.ANTHROPIC_API_KEY:
        logger.warning(
            "ANTHROPIC_API_KEY is not set; verification rows will stay pending"
        )

    engine = create_async_engine(str(settings.DATABASE_URL))
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    while True:
        async with session_factory() as db:
            # One at a time: each is a paid agent run bounded at five minutes,
            # and a batch holds one database connection and its row locks for
            # the whole of it.
            completed = await run_pending_checks(db, limit=1, names=AGENTIC_CHECKS)
        if completed:
            logger.info("completed %d verification(s)", completed)
        if once:
            return
        await asyncio.sleep(interval)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--once", action="store_true", help="single pass, then exit")
    parser.add_argument("--interval", type=float, default=10.0, help="seconds between passes")
    args = parser.parse_args()
    asyncio.run(main(args.once, args.interval))
