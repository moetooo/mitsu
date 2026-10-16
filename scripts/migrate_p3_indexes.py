"""
P3 Database Performance Migration Script:
1. Enable `pg_trgm` extension.
2. Drop legacy IVFFlat vector index (`idx_manga_embedding`) if present.
3. Create GIN Trigram indexes on `title_english`, `title_romaji`, and `title_native` for sub-millisecond title matching.
4. Create HNSW index (`idx_manga_embedding_hnsw`) with boosted maintenance_work_mem (512MB) and partition-by-partition execution to prevent OOM/timeouts.
5. Verify created indexes across PostgreSQL catalog.
"""

import sys
import os
import time
import argparse
import asyncio
from typing import List, Tuple

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from app.config import settings

MIGRATION_STATEMENTS: List[Tuple[str, str]] = [
    (
        "Enable pg_trgm Extension",
        "CREATE EXTENSION IF NOT EXISTS pg_trgm;"
    ),
    (
        "Drop Legacy IVFFlat Index (if present)",
        "DROP INDEX IF EXISTS idx_manga_embedding;"
    ),
    (
        "Create Trigram Index on title_english",
        "CREATE INDEX IF NOT EXISTS idx_manga_title_english_trgm ON manga USING gin (title_english gin_trgm_ops);"
    ),
    (
        "Create Trigram Index on title_romaji",
        "CREATE INDEX IF NOT EXISTS idx_manga_title_romaji_trgm ON manga USING gin (title_romaji gin_trgm_ops);"
    ),
    (
        "Create Trigram Index on title_native",
        "CREATE INDEX IF NOT EXISTS idx_manga_title_native_trgm ON manga USING gin (title_native gin_trgm_ops);"
    ),
    (
        "Create HNSW Vector Cosine Index",
        "CREATE INDEX IF NOT EXISTS idx_manga_embedding_hnsw ON manga USING hnsw (embedding vector_cosine_ops) WITH (m = 16, ef_construction = 64);"
    ),
]


async def run_migration(
    dry_run: bool = False,
    skip_hnsw: bool = False,
    skip_trgm: bool = False,
    mem_mb: int = 512
):
    print("=" * 70)
    print("Mitsu P3 Performance Migration: HNSW Vector Index & pg_trgm Trigrams")
    print("=" * 70)

    if dry_run:
        print("[DRY RUN MODE] The following SQL statements would be executed:\n")
        print(f"-- Session Configuration:\nSET maintenance_work_mem = '{mem_mb}MB';\nSET statement_timeout = 0;\n")
        for desc, sql in MIGRATION_STATEMENTS:
            if skip_hnsw and "hnsw" in sql.lower():
                continue
            if skip_trgm and "trgm" in sql.lower() and "extension" not in sql.lower():
                continue
            print(f"-- {desc}\n{sql}\n")
        print("Dry run completed. No database changes were made.")
        return

    # Create a dedicated migration engine with 30-min command timeout and process-heap worker settings
    migration_engine = create_async_engine(
        settings.DATABASE_URL,
        echo=False,
        pool_pre_ping=True,
        connect_args={
            "command_timeout": 1800,
            "server_settings": {
                "maintenance_work_mem": f"{mem_mb}MB",
                "max_parallel_maintenance_workers": "0",  # Prevents Docker /dev/shm DiskFullError
                "statement_timeout": "0"
            }
        }
    )

    print(f"Connecting to database with maintenance_work_mem={mem_mb}MB and command_timeout=1800s...")
    t_start = time.time()

    try:
        # Step 1: Base setup & Trigram indexes (fast, 1-3s each)
        for desc, sql in MIGRATION_STATEMENTS:
            if "hnsw" in sql.lower():
                continue  # Handled in Step 2 with partition awareness
            if skip_trgm and "trgm" in sql.lower() and "extension" not in sql.lower():
                print(f"Skipping: {desc}")
                continue

            print(f"Executing: {desc} ...", end=" ", flush=True)
            step_start = time.time()
            # Execute in its own transaction so each step is committed immediately
            async with migration_engine.begin() as conn:
                await conn.execute(text(sql))
            elapsed = time.time() - step_start
            print(f"DONE ({elapsed:.2f}s)")

        # Step 2: HNSW Vector Indexing
        if not skip_hnsw:
            # Check if manga is partitioned
            async with migration_engine.connect() as conn:
                res = await conn.execute(text("""
                    SELECT inhrelid::regclass::text AS child_table
                    FROM pg_inherits
                    WHERE inhparent = 'manga'::regclass
                    ORDER BY inhrelid::regclass::text;
                """))
                partitions = [r[0] for r in res.fetchall()]

            if partitions:
                print(f"\nDetected {len(partitions)} partitioned child tables for 'manga'.")
                print("Building HNSW vector index partition-by-partition for maximum stability...")
                for idx, part in enumerate(partitions, 1):
                    # Clean partition name for index naming
                    part_idx_name = f"idx_{part}_embedding_hnsw"
                    sql_part = f"CREATE INDEX IF NOT EXISTS {part_idx_name} ON {part} USING hnsw (embedding vector_cosine_ops) WITH (m = 16, ef_construction = 64);"
                    print(f"  [{idx}/{len(partitions)}] Building HNSW on {part} ...", end=" ", flush=True)
                    step_start = time.time()
                    async with migration_engine.begin() as conn:
                        await conn.execute(text(sql_part))
                    elapsed = time.time() - step_start
                    print(f"DONE ({elapsed:.2f}s)")

                # Finally attach/create on parent table
                print("Attaching HNSW vector index to parent 'manga' table ...", end=" ", flush=True)
                step_start = time.time()
                async with migration_engine.begin() as conn:
                    await conn.execute(text(
                        "CREATE INDEX IF NOT EXISTS idx_manga_embedding_hnsw ON manga USING hnsw (embedding vector_cosine_ops) WITH (m = 16, ef_construction = 64);"
                    ))
                elapsed = time.time() - step_start
                print(f"DONE ({elapsed:.2f}s)")
            else:
                # Non-partitioned table: execute directly
                print("Executing: Create HNSW Vector Cosine Index on manga ...", end=" ", flush=True)
                step_start = time.time()
                async with migration_engine.begin() as conn:
                    await conn.execute(text(
                        "CREATE INDEX IF NOT EXISTS idx_manga_embedding_hnsw ON manga USING hnsw (embedding vector_cosine_ops) WITH (m = 16, ef_construction = 64);"
                    ))
                elapsed = time.time() - step_start
                print(f"DONE ({elapsed:.2f}s)")
        else:
            print("\nSkipping HNSW vector index creation (--skip-hnsw).")

        # Step 3: Verification
        print("-" * 70)
        print("Verifying created indexes in PostgreSQL catalog...")
        async with migration_engine.connect() as conn:
            res = await conn.execute(text("""
                SELECT indexname, tablename, indexdef 
                FROM pg_indexes 
                WHERE tablename LIKE 'manga%' 
                  AND (
                    indexname LIKE '%hnsw%' 
                    OR indexname LIKE '%trgm%'
                  )
                ORDER BY tablename, indexname;
            """))
            rows = res.fetchall()

            if rows:
                print(f"Found {len(rows)} verified P3 indexes:")
                for name, tbl, defn in rows:
                    print(f"  ✓ [{tbl}] {name}")
            else:
                print("  Note: No matching P3 indexes found.")

        total_elapsed = time.time() - t_start
        print("=" * 70)
        print(f"✓ P3 Performance Migration completed successfully in {total_elapsed:.2f}s!")
        print("=" * 70)

    except Exception as exc:
        print(f"\n[ERROR] Migration failed: {exc}", file=sys.stderr)
        raise
    finally:
        await migration_engine.dispose()


def main():
    parser = argparse.ArgumentParser(description="P3 Migration: HNSW vector index & pg_trgm title indexes")
    parser.add_argument("--dry-run", action="store_true", help="Preview SQL statements without executing")
    parser.add_argument("--skip-hnsw", action="store_true", help="Skip HNSW vector index creation")
    parser.add_argument("--skip-trgm", action="store_true", help="Skip Trigram GIN title indexes")
    parser.add_argument("--mem", type=int, default=128, help="maintenance_work_mem in MB (default: 128)")
    args = parser.parse_args()

    asyncio.run(run_migration(
        dry_run=args.dry_run,
        skip_hnsw=args.skip_hnsw,
        skip_trgm=args.skip_trgm,
        mem_mb=args.mem
    ))


if __name__ == "__main__":
    main()
