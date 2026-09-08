"""
Drains the argument check queue, except the agentic checks.

Run continuously:   python -m scripts.run_checks
Run one pass:       python -m scripts.run_checks --once

Checks run in sequence per argument; this drains whatever is pending. The
agentic checks are drained by ``scripts/run_verification.py`` instead, so a
minutes-long agent run cannot stall every other argument's cheap checks.
"""
import argparse
import asyncio
import logging

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.check_runner import FAST_CHECKS, missing_check_functions, run_pending_checks
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
            completed = await run_pending_checks(db, names=FAST_CHECKS)
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
