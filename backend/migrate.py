"""
Idempotent database migrations. Safe to run multiple times.
Runs outside of alembic for simplicity in CI/CD.
"""
import asyncio
import os
import uuid

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

    # 4. paper_revision table + initial backfill
    has_paper_revision = await conn.fetchval(
        "SELECT to_regclass('public.paper_revision')"
    )
    if not has_paper_revision:
        await conn.execute(
            """
            CREATE TABLE paper_revision (
                id uuid PRIMARY KEY,
                paper_id uuid NOT NULL REFERENCES paper(id),
                version integer NOT NULL,
                created_by_id uuid NOT NULL REFERENCES actor(id),
                title varchar NOT NULL,
                abstract text NOT NULL,
                pdf_url varchar,
                github_repo_url varchar,
                preview_image_url varchar,
                changelog text,
                created_at timestamp DEFAULT now(),
                updated_at timestamp DEFAULT now(),
                CONSTRAINT uq_paper_revision_paper_version UNIQUE (paper_id, version)
            )
            """
        )
        await conn.execute("CREATE INDEX ix_paper_revision_paper_id ON paper_revision (paper_id)")
        await conn.execute("CREATE INDEX ix_paper_revision_created_by_id ON paper_revision (created_by_id)")
        await conn.execute("CREATE INDEX ix_paper_revision_title ON paper_revision (title)")
        print("Migrated: added paper_revision table")
    else:
        print("Skip: paper_revision table already exists")

    missing_revision_rows = await conn.fetch(
        """
        SELECT p.id, p.submitter_id, p.title, p.abstract, p.pdf_url, p.github_repo_url,
               p.preview_image_url, p.created_at, p.updated_at
        FROM paper p
        WHERE NOT EXISTS (
            SELECT 1
            FROM paper_revision pr
            WHERE pr.paper_id = p.id
        )
        """
    )
    if missing_revision_rows:
        await conn.executemany(
            """
            INSERT INTO paper_revision (
                id,
                paper_id,
                version,
                created_by_id,
                title,
                abstract,
                pdf_url,
                github_repo_url,
                preview_image_url,
                changelog,
                created_at,
                updated_at
            ) VALUES ($1, $2, 1, $3, $4, $5, $6, $7, $8, NULL, $9, $10)
            """,
            [
                (
                    uuid.uuid4(),
                    row["id"],
                    row["submitter_id"],
                    row["title"],
                    row["abstract"],
                    row["pdf_url"],
                    row["github_repo_url"],
                    row["preview_image_url"],
                    row["created_at"],
                    row["updated_at"],
                )
                for row in missing_revision_rows
            ],
        )
        print(f"Migrated: backfilled {len(missing_revision_rows)} initial paper revisions")
    else:
        print("Skip: paper revisions already backfilled")

    await conn.close()
    print("Migrations complete")


if __name__ == "__main__":
    asyncio.run(migrate())
