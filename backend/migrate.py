"""
Idempotent database migrations. Safe to run multiple times.
Runs outside of alembic for simplicity in CI/CD.
"""
import asyncio
import os

import asyncpg


async def migrate():
    conn = await asyncpg.connect(
        user=os.environ["POSTGRES_USER"],
        password=os.environ["POSTGRES_PASSWORD"],
        database=os.environ["POSTGRES_DB"],
        host=os.environ.get("POSTGRES_SERVER", "localhost"),
        port=int(os.environ.get("POSTGRES_PORT", 5432)),
    )

    # 1. domain (varchar) -> domains (varchar[])
    col = await conn.fetchval(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_name='paper' AND column_name='domain'"
    )
    if col:
        await conn.execute(
            "ALTER TABLE paper ALTER COLUMN domain TYPE varchar[] USING ARRAY[domain]"
        )
        await conn.execute("ALTER TABLE paper RENAME COLUMN domain TO domains")
        print("Migrated: domain -> domains")
    else:
        print("Skip: domains already migrated")

    # 2. owner_id nullable (for self-registered agents)
    is_nullable = await conn.fetchval(
        "SELECT is_nullable FROM information_schema.columns "
        "WHERE table_name='delegated_agent' AND column_name='owner_id'"
    )
    if is_nullable == "NO":
        await conn.execute(
            "ALTER TABLE delegated_agent ALTER COLUMN owner_id DROP NOT NULL"
        )
        print("Migrated: owner_id now nullable")
    else:
        print("Skip: owner_id already nullable")

    # 3. description column on delegated_agent
    has_desc = await conn.fetchval(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_name='delegated_agent' AND column_name='description'"
    )
    if not has_desc:
        await conn.execute("ALTER TABLE delegated_agent ADD COLUMN description TEXT")
        print("Migrated: added description column")
    else:
        print("Skip: description already exists")

    await conn.close()
    print("Migrations complete")


if __name__ == "__main__":
    asyncio.run(migrate())
