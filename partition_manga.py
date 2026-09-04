import asyncio
import os
import sys

# Add root directory to python path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from app.db import engine
from sqlalchemy import text

async def partition_manga_table():
    async with engine.begin() as conn:
        try:
            print("Starting table partitioning migration...")
            
            # 1. Rename existing table and indexes
            await conn.execute(text("ALTER TABLE manga RENAME TO manga_old;"))
            await conn.execute(text("ALTER INDEX manga_pkey RENAME TO manga_old_pkey;"))
            # Note: We would drop old foreign keys here if they existed on the database level
            await conn.execute(text("ALTER TABLE recommendations_edges DROP CONSTRAINT IF EXISTS recommendations_edges_manga_id_from_fkey;"))
            await conn.execute(text("ALTER TABLE recommendations_edges DROP CONSTRAINT IF EXISTS recommendations_edges_manga_id_to_fkey;"))

            # 2. Create the new partitioned table
            await conn.execute(text("""
                CREATE TABLE manga (
                    id SERIAL,
                    anilist_id INTEGER,
                    mal_id INTEGER,
                    mangadex_id VARCHAR,
                    title_romaji TEXT,
                    title_english TEXT,
                    title_native TEXT,
                    synopsis TEXT,
                    genres TEXT[],
                    tags JSONB,
                    status TEXT,
                    start_year INTEGER,
                    chapters INTEGER,
                    volumes INTEGER,
                    average_score INTEGER,
                    popularity INTEGER,
                    cover_image_url TEXT,
                    banner_image TEXT,
                    site_url TEXT,
                    embedding vector(384),
                    similar_mangas JSONB,
                    created_at TIMESTAMP WITH TIME ZONE DEFAULT now(),
                    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now(),
                    PRIMARY KEY (id, start_year),
                    CONSTRAINT uq_manga_anilist_id UNIQUE (anilist_id, start_year),
                    CONSTRAINT uq_manga_mal_id UNIQUE (mal_id, start_year),
                    CONSTRAINT uq_manga_mangadex_id UNIQUE (mangadex_id, start_year)
                ) PARTITION BY RANGE (start_year);
            """))
            print("Created partitioned manga table.")

            # 3. Create partitions by decade
            partitions = [
                ("pre_1980", "MINVALUE", "1980"),
                ("1980s", "1980", "1990"),
                ("1990s", "1990", "2000"),
                ("2000s", "2000", "2010"),
                ("2010s", "2010", "2020"),
                ("2020s", "2020", "2030"),
                ("post_2030", "2030", "MAXVALUE")
            ]
            for name, start, end in partitions:
                await conn.execute(text(f"CREATE TABLE manga_{name} PARTITION OF manga FOR VALUES FROM ({start}) TO ({end});"))
            
            # Default partition for null years
            await conn.execute(text("CREATE TABLE manga_default PARTITION OF manga DEFAULT;"))
            print("Created all decade partitions.")

            # 4. Migrate data
            print("Migrating data from manga_old to new partitioned table...")
            await conn.execute(text("INSERT INTO manga SELECT * FROM manga_old;"))
            
            # 5. Drop old table
            await conn.execute(text("DROP TABLE manga_old;"))
            print("Successfully migrated data and dropped old table.")

            # Re-create indexes
            await conn.execute(text("CREATE INDEX idx_manga_genres ON manga USING gin (genres);"))
            await conn.execute(text("CREATE INDEX idx_manga_status ON manga (status);"))
            await conn.execute(text("CREATE INDEX idx_manga_start_year ON manga (start_year);"))
            print("Re-created indexes on partitioned table.")
            
        except Exception as e:
            print(f"Error during partitioning: {e}")
            raise e

if __name__ == "__main__":
    asyncio.run(partition_manga_table())
