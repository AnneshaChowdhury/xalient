import asyncio
import logging
import os
import re
from datetime import datetime, timezone
from urllib.parse import quote_plus, urljoin

from dotenv import load_dotenv
from playwright.async_api import BrowserContext, Page, TimeoutError as PlaywrightTimeoutError
from playwright.async_api import async_playwright

import agent
from database import init_db, insert_post, post_exists


load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)
logger = logging.getLogger("xreach.scraper")

CHROME_PROFILE_PATH = os.getenv("CHROME_PROFILE_PATH", "./chrome_profile")
SEARCH_QUERIES = [
    query.strip()
    for query in os.getenv(
        "SEARCH_QUERIES",
        "hiring data engineer,hiring AI engineer,founding engineer,"
        "looking for ML engineer,join our team early stage",
    ).split(",")
    if query.strip()
]
POLL_INTERVAL_MINUTES = float(os.getenv("POLL_INTERVAL_MINUTES", "3"))
MIN_FOLLOWER_COUNT = int(os.getenv("MIN_FOLLOWER_COUNT", "500"))
X_BASE_URL = "https://x.com"

LAST_POLL_TIME: str | None = None
IS_RUNNING = False


def get_last_poll_time() -> str | None:
    return LAST_POLL_TIME


def _parse_count(text: str) -> int | None:
    match = re.search(r"([\d,.]+)\s*([KMBkmb]?)", text)
    if not match:
        return None
    value = float(match.group(1).replace(",", ""))
    suffix = match.group(2).lower()
    multiplier = {"k": 1_000, "m": 1_000_000, "b": 1_000_000_000}.get(suffix, 1)
    return int(value * multiplier)


async def _safe_text(locator) -> str:
    try:
        return (await locator.inner_text(timeout=2_000)).strip()
    except Exception:
        return ""


async def _extract_follower_count(context: BrowserContext, profile_url: str) -> int | None:
    page = await context.new_page()
    try:
        await page.goto(profile_url, wait_until="domcontentloaded", timeout=20_000)
        await page.wait_for_timeout(2_500)
        links = await page.locator("a[href$='/verified_followers'], a[href$='/followers']").all()
        for link in links:
            text = await _safe_text(link)
            if "follower" in text.lower():
                count = _parse_count(text)
                if count is not None:
                    return count

        body = await _safe_text(page.locator("body"))
        match = re.search(r"([\d,.]+\s*[KMBkmb]?)\s+Followers", body)
        if match:
            return _parse_count(match.group(1))
    except Exception as exc:
        logger.warning("Could not read follower count from %s: %s", profile_url, exc)
    finally:
        await page.close()
    return None


async def _extract_tweets_from_page(page: Page, context: BrowserContext) -> list[dict]:
    tweets: list[dict] = []
    articles = await page.locator("article[data-testid='tweet']").all()

    for article in articles:
        try:
            tweet_text = await _safe_text(article.locator("[data-testid='tweetText']").first())
            status_links = await article.locator("a[href*='/status/']").all()
            tweet_url = None
            timestamp = None
            for link in status_links:
                href = await link.get_attribute("href")
                if href and "/status/" in href:
                    tweet_url = urljoin(X_BASE_URL, href.split("?")[0])
                    break

            time_locator = article.locator("time").first()
            if await time_locator.count():
                timestamp = await time_locator.get_attribute("datetime")

            user_links = await article.locator("a[href^='/'][role='link']").all()
            author_handle = None
            profile_url = None
            for link in user_links:
                href = await link.get_attribute("href")
                if not href:
                    continue
                parts = href.strip("/").split("/")
                if len(parts) == 1 and parts[0] not in {"i", "home", "search"}:
                    author_handle = f"@{parts[0]}"
                    profile_url = urljoin(X_BASE_URL, href)
                    break

            article_text = await _safe_text(article)
            author_name = article_text.splitlines()[0] if article_text else None

            if not tweet_text or not tweet_url or not author_handle or not profile_url:
                continue

            if post_exists(tweet_url):
                continue

            follower_count = await _extract_follower_count(context, profile_url)
            if follower_count is None:
                logger.info(
                    "Follower count unknown for %s; storing as threshold value %s",
                    author_handle,
                    MIN_FOLLOWER_COUNT,
                )
                follower_count = MIN_FOLLOWER_COUNT

            if follower_count < MIN_FOLLOWER_COUNT:
                logger.info(
                    "Skipping %s with %s followers below threshold %s",
                    author_handle,
                    follower_count,
                    MIN_FOLLOWER_COUNT,
                )
                continue

            tweets.append(
                {
                    "tweet_url": tweet_url,
                    "author_handle": author_handle,
                    "author_name": author_name,
                    "follower_count": follower_count,
                    "tweet_text": tweet_text,
                    "timestamp": timestamp,
                }
            )
        except Exception as exc:
            logger.warning("Could not extract a tweet card: %s", exc)
    return tweets


async def poll_once(page: Page, context: BrowserContext) -> int:
    global LAST_POLL_TIME

    init_db()
    inserted = 0
    for query in SEARCH_QUERIES:
        try:
            url = f"{X_BASE_URL}/search?q={quote_plus(query)}&src=typed_query&f=live"
            logger.info("Polling X search: %s", query)
            await page.goto(url, wait_until="domcontentloaded", timeout=30_000)
            await page.wait_for_timeout(4_000)
            tweets = await _extract_tweets_from_page(page, context)
            for tweet in tweets:
                if insert_post(**tweet):
                    inserted += 1
        except PlaywrightTimeoutError:
            logger.warning("Timed out polling query: %s", query)
        except Exception as exc:
            logger.exception("Polling query failed for %s: %s", query, exc)

    LAST_POLL_TIME = datetime.now(timezone.utc).isoformat()
    if inserted:
        logger.info("Inserted %s new posts; starting agent processing", inserted)
        await asyncio.to_thread(agent.process_new_posts)
    else:
        logger.info("No new posts inserted this cycle")
    return inserted


async def run_polling_loop() -> None:
    global IS_RUNNING

    if IS_RUNNING:
        logger.info("Scraper loop already running")
        return

    IS_RUNNING = True
    init_db()
    async with async_playwright() as playwright:
        context = await playwright.chromium.launch_persistent_context(
            user_data_dir=CHROME_PROFILE_PATH,
            headless=False,
            viewport={"width": 1440, "height": 1000},
        )
        page = context.pages[0] if context.pages else await context.new_page()
        logger.info("Browser opened. Log into X manually on first run if needed.")

        try:
            while True:
                try:
                    await poll_once(page, context)
                except Exception as exc:
                    logger.exception("Polling cycle failed but loop will continue: %s", exc)
                await asyncio.sleep(max(POLL_INTERVAL_MINUTES, 0.25) * 60)
        finally:
            IS_RUNNING = False
            await context.close()


if __name__ == "__main__":
    asyncio.run(run_polling_loop())
