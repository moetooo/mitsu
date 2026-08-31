import asyncio
import os
import sys

# Add root directory to python path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from app.db import engine
from sqlalchemy import text

async def add_column():
    async with engine.begin() as conn:
        try:
            await conn.execute(text("ALTER TABLE manga ADD COLUMN similar_mangas JSONB;"))
            print("Successfully added similar_mangas column to manga table.")
        except Exception as e:
            if 'already exists' in str(e).lower():
                print("Column similar_mangas already exists.")
            else:
                print(f"Error adding column: {e}")

if __name__ == "__main__":
    asyncio.run(add_column())
