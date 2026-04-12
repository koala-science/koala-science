"""
Create database schema directly from SQLAlchemy models.
Use this for fresh databases (e.g., staging) instead of running migrations.

Usage:
    python -m scripts.create_schema
"""
import asyncio
from app.db.base import Base
from app.db.session import engine


async def main():
    print("Creating schema from models...")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    print("Schema created.")
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
