"""
Chinta Notebook — simple note CRUD backed by PostgreSQL.

M1: single-user (user_id=1), no auth enforcement here (gateway handles auth).
"""
import logging
import os

import asyncpg
from fastapi import FastAPI, HTTPException
from log import setup_logging
from pydantic import BaseModel

setup_logging()
logger = logging.getLogger("chinta-notebook")

DB_DSN = os.environ.get(
    "DATABASE_URL",
    "postgresql://chinta_user:chinta_password@localhost:5432/chinta",
)

DEFAULT_USER_ID = 1

app = FastAPI(
    title="Chinta Notebook",
    version="0.1.0",
    description="Simple note-taking service",
)

pool: asyncpg.Pool | None = None


@app.on_event("startup")
async def startup():
    global pool
    logger.info("Connecting to database", extra={"dsn": DB_DSN.split("@")[-1]})
    pool = await asyncpg.create_pool(dsn=DB_DSN, min_size=2, max_size=10)
    logger.info("Database pool created")


@app.on_event("shutdown")
async def shutdown():
    if pool:
        await pool.close()
        logger.info("Database pool closed")


# --- Models ---

class NoteCreate(BaseModel):
    title: str
    body: str = ""
    tags: list[str] = []


class NoteOut(BaseModel):
    id: int
    title: str
    body: str
    tags: list[str]
    created_at: str
    updated_at: str


# --- Helpers ---

async def _get_or_create_tag(conn, name: str) -> int:
    row = await conn.fetchrow("SELECT id FROM tags WHERE name = $1", name)
    if row:
        return row["id"]
    row = await conn.fetchrow(
        "INSERT INTO tags (name) VALUES ($1) ON CONFLICT (name) DO UPDATE SET name=EXCLUDED.name RETURNING id",
        name,
    )
    return row["id"]


async def _note_tags(conn, note_id: int) -> list[str]:
    rows = await conn.fetch(
        "SELECT t.name FROM tags t JOIN note_tags nt ON nt.tag_id = t.id WHERE nt.note_id = $1 ORDER BY t.name",
        note_id,
    )
    return [r["name"] for r in rows]


def _row_to_note(row, tags: list[str]) -> dict:
    return {
        "id": row["id"],
        "title": row["title"],
        "body": row["body"],
        "tags": tags,
        "created_at": row["created_at"].isoformat(),
        "updated_at": row["updated_at"].isoformat(),
    }


# --- Routes ---

@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/notes", response_model=list[NoteOut])
async def list_notes(tag: str | None = None):
    """List all notes, optionally filtered by tag."""
    async with pool.acquire() as conn:
        if tag:
            rows = await conn.fetch(
                """
                SELECT n.* FROM notes n
                JOIN note_tags nt ON nt.note_id = n.id
                JOIN tags t ON t.id = nt.tag_id
                WHERE n.user_id = $1 AND t.name = $2
                ORDER BY n.created_at DESC
                """,
                DEFAULT_USER_ID,
                tag,
            )
        else:
            rows = await conn.fetch(
                "SELECT * FROM notes WHERE user_id = $1 ORDER BY created_at DESC",
                DEFAULT_USER_ID,
            )
        result = []
        for row in rows:
            tags = await _note_tags(conn, row["id"])
            result.append(_row_to_note(row, tags))
        return result


@app.post("/notes", response_model=NoteOut, status_code=201)
async def create_note(note: NoteCreate):
    """Create a new note with optional tags."""
    logger.info("Creating note", extra={"title": note.title, "tags": note.tags})
    async with pool.acquire() as conn:
        async with conn.transaction():
            row = await conn.fetchrow(
                """
                INSERT INTO notes (user_id, title, body)
                VALUES ($1, $2, $3)
                RETURNING *
                """,
                DEFAULT_USER_ID,
                note.title,
                note.body,
            )
            for tag_name in note.tags:
                tag_id = await _get_or_create_tag(conn, tag_name)
                await conn.execute(
                    "INSERT INTO note_tags (note_id, tag_id) VALUES ($1, $2) ON CONFLICT DO NOTHING",
                    row["id"],
                    tag_id,
                )
            tags = await _note_tags(conn, row["id"])
    return _row_to_note(row, tags)


@app.get("/notes/{note_id}", response_model=NoteOut)
async def get_note(note_id: int):
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM notes WHERE id = $1 AND user_id = $2",
            note_id,
            DEFAULT_USER_ID,
        )
        if not row:
            raise HTTPException(status_code=404, detail="Note not found")
        tags = await _note_tags(conn, row["id"])
    return _row_to_note(row, tags)


@app.delete("/notes/{note_id}", status_code=204)
async def delete_note(note_id: int):
    async with pool.acquire() as conn:
        result = await conn.execute(
            "DELETE FROM notes WHERE id = $1 AND user_id = $2",
            note_id,
            DEFAULT_USER_ID,
        )
        if result == "DELETE 0":
            raise HTTPException(status_code=404, detail="Note not found")
    logger.info("Deleted note", extra={"note_id": note_id})


if __name__ == "__main__":
    import uvicorn

    port = int(os.environ.get("PORT", "8085"))
    uvicorn.run("app:app", host="0.0.0.0", port=port, reload=True)
