import asyncio
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

import scraper
from database import db_connection, init_db


app = FastAPI(title="Xalient")


class DraftUpdate(BaseModel):
    reply_draft: str | None = None
    dm_draft: str | None = None


@app.on_event("startup")
async def startup() -> None:
    init_db()
    asyncio.create_task(scraper.run_polling_loop())


@app.get("/", response_class=HTMLResponse)
async def dashboard() -> str:
    return Path("dashboard.html").read_text(encoding="utf-8")


@app.get("/drafts")
async def get_drafts() -> list[dict[str, Any]]:
    with db_connection() as conn:
        rows = conn.execute(
            """
            SELECT
                drafts.id,
                drafts.post_id,
                drafts.is_hiring,
                drafts.confidence,
                drafts.reply_draft,
                drafts.dm_draft,
                drafts.status,
                drafts.created_at,
                posts.tweet_url,
                posts.author_handle,
                posts.author_name,
                posts.follower_count,
                posts.tweet_text,
                posts.timestamp
            FROM drafts
            JOIN posts ON posts.id = drafts.post_id
            WHERE drafts.status = 'pending'
            ORDER BY drafts.created_at DESC, drafts.id DESC
            """
        ).fetchall()
        return [dict(row) for row in rows]


def _update_status(draft_id: int, status: str, payload: DraftUpdate | None = None) -> dict:
    with db_connection() as conn:
        existing = conn.execute(
            "SELECT id FROM drafts WHERE id = ?",
            (draft_id,),
        ).fetchone()
        if not existing:
            raise HTTPException(status_code=404, detail="Draft not found")

        if payload:
            conn.execute(
                """
                UPDATE drafts
                SET
                    reply_draft = COALESCE(?, reply_draft),
                    dm_draft = COALESCE(?, dm_draft)
                WHERE id = ?
                """,
                (payload.reply_draft, payload.dm_draft, draft_id),
            )

        conn.execute("UPDATE drafts SET status = ? WHERE id = ?", (status, draft_id))
    return {"ok": True, "id": draft_id, "status": status}


@app.post("/drafts/{draft_id}/approve")
async def approve_draft(draft_id: int, payload: DraftUpdate | None = None) -> dict:
    return _update_status(draft_id, "approved", payload)


@app.post("/drafts/{draft_id}/skip")
async def skip_draft(draft_id: int, payload: DraftUpdate | None = None) -> dict:
    return _update_status(draft_id, "skipped", payload)


@app.get("/stats")
async def get_stats() -> dict[str, Any]:
    with db_connection() as conn:
        total_posts = conn.execute("SELECT COUNT(*) AS count FROM posts").fetchone()["count"]
        pending = conn.execute(
            "SELECT COUNT(*) AS count FROM drafts WHERE status = 'pending'"
        ).fetchone()["count"]
        approved = conn.execute(
            "SELECT COUNT(*) AS count FROM drafts WHERE status = 'approved'"
        ).fetchone()["count"]
        skipped = conn.execute(
            "SELECT COUNT(*) AS count FROM drafts WHERE status = 'skipped'"
        ).fetchone()["count"]

    return {
        "total_posts_scraped": total_posts,
        "pending_drafts": pending,
        "approved": approved,
        "skipped": skipped,
        "last_poll_time": scraper.get_last_poll_time(),
    }
