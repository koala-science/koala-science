"""
Drains the argument check queue.

Run continuously:   python -m scripts.run_checks
Run one pass:       python -m scripts.run_checks --once

Nothing is registered in ``CHECKS`` yet, so this currently has nothing to do.
It exists so that adding a check does not also require inventing a way to run it.
"""
import argparse
import asyncio
import logging

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.check_runner import missing_check_functions, run_pending_checks
from app.core.config import settings

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("run_checks")


async def main(once: bool, interval: float) -> None:
    missing = missing_check_functions()
    if missing:
        logger.warning(
            "queued with no function to run them: %s", ", ".join(sorted(missing))
        )

    engine = create_async_engine(str(settings.DATABASE_URL))
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    while True:
        async with session_factory() as db:
            completed = await run_pending_checks(db)
        if completed:
            logger.info("completed %d check(s)", completed)
        if once:
            return
        await asyncio.sleep(interval)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--once", action="store_true", help="single pass, then exit")
    parser.add_argument("--interval", type=float, default=5.0, help="seconds between passes")
    args = parser.parse_args()
    asyncio.run(main(args.once, args.interval))
