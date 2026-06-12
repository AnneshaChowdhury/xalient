import json
import logging
import os
from typing import Any

import requests
from dotenv import load_dotenv

from database import db_connection, init_db


load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)
logger = logging.getLogger("xreach.agent")

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434").rstrip("/")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3.2")
PORTFOLIO_URL = os.getenv("PORTFOLIO_URL", "https://annesha.dev")
CONFIDENCE_THRESHOLD = 0.75
TIMEOUT_SECONDS = 45

ANNESHA_CONTEXT = f"""
Name: Annesha
Role: AI & Big Data Engineer
Founder of: Crisisense, a neuro-symbolic AI platform for critical infrastructure resilience;
and Acurelli, a document trust/observability layer for AI/RAG systems.
Skills: Python, data engineering, Spark, Kafka, FastAPI, RAG systems,
neuro-symbolic AI, AWS/GCP.
Portfolio: {PORTFOLIO_URL}
Target roles: founding engineer, data engineer, AI/ML engineer at early-stage startups.
""".strip()


def _ollama_generate(prompt: str) -> str | None:
    try:
        response = requests.post(
            f"{OLLAMA_URL}/api/generate",
            json={
                "model": OLLAMA_MODEL,
                "prompt": prompt,
                "stream": False,
                "format": "json",
            },
            timeout=TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        return response.json().get("response", "")
    except requests.RequestException as exc:
        logger.warning("Ollama request failed: %s", exc)
    except ValueError as exc:
        logger.warning("Ollama returned invalid response JSON: %s", exc)
    return None


def _parse_json(raw: str | None) -> dict[str, Any] | None:
    if not raw:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        start = raw.find("{")
        end = raw.rfind("}")
        if start != -1 and end != -1 and end > start:
            try:
                return json.loads(raw[start : end + 1])
            except json.JSONDecodeError as exc:
                logger.warning("Could not parse JSON from Ollama text: %s", exc)
        else:
            logger.warning("Ollama response did not contain a JSON object")
    return None


def _classify_post(tweet_text: str) -> dict[str, Any] | None:
    prompt = f"""
You are filtering X/Twitter posts for real hiring opportunities relevant to Annesha.

Return strict JSON only:
{{
  "is_hiring_post": true,
  "confidence": 0.0,
  "role_type": "founding engineer | data engineer | AI/ML engineer | other"
}}

Only mark true when the post is likely hiring, recruiting, or explicitly looking
for engineering candidates. Prefer early-stage startup engineering roles.

Tweet:
{tweet_text}
""".strip()
    return _parse_json(_ollama_generate(prompt))


def _generate_drafts(tweet_text: str, author_name: str | None) -> dict[str, str] | None:
    prompt = f"""
You draft concise, human-reviewed outreach for Annesha.

Context:
{ANNESHA_CONTEXT}

Tweet author name: {author_name or "unknown"}
Tweet:
{tweet_text}

Return strict JSON only:
{{
  "reply_draft": "Under 280 chars. Genuine, technical tone. Mention relevant background and include {PORTFOLIO_URL}.",
  "dm_draft": "3-4 sentences. Personal, specific to what the company appears to be building from the tweet. Mention relevant fit without sounding generic."
}}

Do not claim Annesha has applied. Do not imply auto-sending. Keep it natural.
""".strip()
    data = _parse_json(_ollama_generate(prompt))
    if not data:
        return None

    reply = str(data.get("reply_draft", "")).strip()
    dm = str(data.get("dm_draft", "")).strip()
    if not reply or not dm:
        return None
    if len(reply) > 280:
        reply = reply[:277].rstrip() + "..."
    return {"reply_draft": reply, "dm_draft": dm}


def _mark_processed(post_id: int) -> None:
    with db_connection() as conn:
        conn.execute("UPDATE posts SET processed = 1 WHERE id = ?", (post_id,))


def process_new_posts() -> None:
    init_db()
    with db_connection() as conn:
        posts = conn.execute(
            """
            SELECT id, tweet_text, author_name
            FROM posts
            WHERE processed = 0
            ORDER BY id ASC
            """
        ).fetchall()

    for post in posts:
        post_id = int(post["id"])
        try:
            classification = _classify_post(post["tweet_text"])
            if not classification:
                logger.info("Skipping post %s after classification failure", post_id)
                _mark_processed(post_id)
                continue

            is_hiring = bool(classification.get("is_hiring_post"))
            confidence = float(classification.get("confidence", 0.0) or 0.0)

            if not is_hiring or confidence <= CONFIDENCE_THRESHOLD:
                logger.info(
                    "Post %s not confident enough: is_hiring=%s confidence=%.2f",
                    post_id,
                    is_hiring,
                    confidence,
                )
                _mark_processed(post_id)
                continue

            drafts = _generate_drafts(post["tweet_text"], post["author_name"])
            if not drafts:
                logger.info("Skipping post %s after draft generation failure", post_id)
                _mark_processed(post_id)
                continue

            with db_connection() as conn:
                conn.execute(
                    """
                    INSERT INTO drafts (
                        post_id,
                        is_hiring,
                        confidence,
                        reply_draft,
                        dm_draft,
                        status
                    )
                    VALUES (?, ?, ?, ?, ?, 'pending')
                    """,
                    (
                        post_id,
                        1,
                        confidence,
                        drafts["reply_draft"],
                        drafts["dm_draft"],
                    ),
                )
                conn.execute("UPDATE posts SET processed = 1 WHERE id = ?", (post_id,))
            logger.info("Created pending draft for post %s", post_id)
        except Exception as exc:
            logger.exception("Unexpected agent error for post %s: %s", post_id, exc)
            _mark_processed(post_id)


if __name__ == "__main__":
    process_new_posts()
