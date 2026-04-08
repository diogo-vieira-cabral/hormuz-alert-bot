"""
news-alert-bot / bot.py
=======================
A config-driven RSS news monitor that sends Telegram alerts
when articles match keywords you define in config.yaml.

Designed to be reusable: swap config.yaml for any topic
(e.g. Red Sea, Taiwan Strait, oil markets) with zero code changes.

Dependencies:
    pip install requests feedparser pyyaml

Environment variables (set in .env or Railway dashboard):
    TELEGRAM_TOKEN    — your bot token from @BotFather
    TELEGRAM_CHAT_ID  — your personal chat ID (see SETUP.md)

Author: you
"""

import os
import sys
import time
import hashlib
import logging
import requests
import feedparser
import yaml
from datetime import datetime, timezone
from pathlib import Path


# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)


# ── Load .env manually (no python-dotenv needed) ──────────────────────────────
def load_dotenv(path: str = ".env") -> None:
    """
    Reads KEY=VALUE lines from a .env file and sets them as environment
    variables. Skips comments (#) and blank lines. Does NOT override
    variables that are already set in the environment (Railway injects
    them directly, so this only matters for local runs).
    """
    env_file = Path(path)
    if not env_file.exists():
        return
    for line in env_file.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:  # don't override Railway env vars
            os.environ[key] = value


# ── Load config ───────────────────────────────────────────────────────────────
def load_config(path: str = "config.yaml") -> dict:
    """
    Loads the YAML config file. This is where all behaviour lives —
    feeds, keywords, tiers, cooldowns, notification settings.
    Raises a clear error if the file is missing.
    """
    config_file = Path(path)
    if not config_file.exists():
        log.error(
            "config.yaml not found. Copy config.yaml.example to config.yaml and edit it."
        )
        sys.exit(1)
    with open(config_file) as f:
        return yaml.safe_load(f)


# ── Telegram ──────────────────────────────────────────────────────────────────
def send_telegram(token: str, chat_id: str, message: str) -> bool:
    """
    Sends a Telegram message via the Bot API.
    Supports HTML formatting (<b>, <a href=...>, etc.).
    Returns True on success, False on failure (logs the error).
    """
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": message,
        "parse_mode": "HTML",
        "disable_web_page_preview": False,
    }
    try:
        r = requests.post(url, json=payload, timeout=10)
        r.raise_for_status()
        return True
    except requests.exceptions.HTTPError as e:
        log.error("Telegram HTTP error: %s — %s", e, r.text)
    except Exception as e:
        log.error("Telegram send failed: %s", e)
    return False


# ── Article classification ────────────────────────────────────────────────────
def classify_article(title: str, summary: str, tiers: list) -> dict | None:
    """
    Checks an article against each alert tier (in order, most severe first).
    Returns the first matching tier dict, or None if no match.

    Matching is case-insensitive substring search — simple and fast.
    The tier order in config.yaml determines priority, so put your most
    critical tier first.
    """
    combined = (title + " " + summary).lower()
    for tier in tiers:
        # Only process tiers that have notify: true in config
        if not tier.get("notify", True):
            log.debug("Tier '%s' has notify:false — skipping", tier["label"])
            continue
        if any(kw.lower() in combined for kw in tier["keywords"]):
            return tier
    return None


# ── Alert formatting ──────────────────────────────────────────────────────────
def format_alert(tier: dict, title: str, link: str, source: str, topic: str) -> str:
    """
    Builds the Telegram message string.
    Uses HTML formatting (Telegram's parse_mode: HTML).
    """
    now = datetime.now(timezone.utc).strftime("%H:%M UTC · %d %b %Y")
    emoji = tier.get("emoji", "📰")
    label = tier.get("label", "ALERT")
    return (
        f"{emoji} <b>{topic.upper()} — {label}</b>\n\n"
        f"<b>{title}</b>\n\n"
        f"🔗 <a href='{link}'>{source}</a>\n"
        f"🕐 {now}"
    )


# ── Article fingerprint ───────────────────────────────────────────────────────
def article_hash(title: str, link: str) -> str:
    """
    Creates a short unique ID for each article so we never alert twice
    for the same story. Based on title + URL (not publish time, which
    some feeds update inconsistently).
    """
    return hashlib.md5((title + link).encode()).hexdigest()


# ── Feed polling ──────────────────────────────────────────────────────────────
def poll_feeds(
    feeds: list,
    tiers: list,
    topic: str,
    token: str,
    chat_id: str,
    seen: set,
    cooldowns: dict,
    cooldown_hours: float,
    seed_mode: bool = False,
) -> int:
    """
    Fetches all RSS feeds, classifies new articles, and sends alerts.

    seed_mode=True: just populate `seen` without sending any alerts.
    This runs once at startup so old articles don't trigger a flood.

    Returns the number of alerts sent (0 in seed_mode).
    """
    alerts_sent = 0

    for feed_url in feeds:
        try:
            feed = feedparser.parse(feed_url)
        except Exception as e:
            log.warning("Failed to fetch feed %s: %s", feed_url, e)
            continue

        source_name = feed.feed.get("title", feed_url[:50])

        for entry in feed.entries:
            title = entry.get("title", "").strip()
            summary = entry.get("summary", "").strip()
            link = entry.get("link", "").strip()
            uid = article_hash(title, link)

            # Already processed — skip
            if uid in seen:
                continue
            seen.add(uid)

            # Seed mode: just mark as seen, no alerts
            if seed_mode:
                continue

            # Classify against tiers
            tier = classify_article(title, summary, tiers)
            if not tier:
                continue

            # Cooldown check: same article can't re-alert within cooldown window
            now_ts = time.time()
            if now_ts - cooldowns.get(uid, 0) < cooldown_hours * 3600:
                log.debug("Cooldown active — skipping: %s", title[:60])
                continue

            # Send alert
            log.info("[%s] %s | %s", tier["label"], source_name, title[:80])
            msg = format_alert(tier, title, link, source_name, topic)
            if send_telegram(token, chat_id, msg):
                cooldowns[uid] = now_ts
                alerts_sent += 1
                time.sleep(1)  # avoid Telegram rate limit (30 msg/sec global)

    return alerts_sent


# ── Main loop ─────────────────────────────────────────────────────────────────
def main():
    # Load env vars from .env (local dev). Railway sets them directly.
    load_dotenv(".env")

    # Load YAML config
    cfg = load_config("config.yaml")

    # Read secrets from environment
    token = os.environ.get("TELEGRAM_TOKEN", "").strip()
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "").strip()

    if not token or not chat_id:
        log.error(
            "TELEGRAM_TOKEN and TELEGRAM_CHAT_ID must be set.\n"
            "  Local: add them to your .env file\n"
            "  Railway: add them in the Railway dashboard → Variables"
        )
        sys.exit(1)

    # Pull settings from config
    topic = cfg.get("topic", "Alert Bot")
    interval_min = cfg.get("check_interval_minutes", 15)
    cooldown_hours = cfg.get("alert_cooldown_hours", 1)
    feeds = cfg.get("feeds", [])
    tiers = cfg.get("tiers", [])

    if not feeds:
        log.error("No feeds defined in config.yaml")
        sys.exit(1)

    log.info("Starting %s bot", topic)
    log.info(
        "%d feeds | check every %d min | cooldown %gh",
        len(feeds),
        interval_min,
        cooldown_hours,
    )

    # In-memory state (resets on restart — fine for this use case)
    seen: set = set()  # article UIDs already processed
    cooldowns: dict = {}  # uid -> timestamp of last alert

    # ── Startup: seed seen articles so we don't blast old news ────────────────
    log.info("Seeding existing articles (no alerts on first scan)...")
    poll_feeds(
        feeds,
        tiers,
        topic,
        token,
        chat_id,
        seen,
        cooldowns,
        cooldown_hours,
        seed_mode=True,
    )
    log.info("Seeded %d articles. Live monitoring starts now.", len(seen))

    # Send startup confirmation to Telegram
    active_tiers = [t for t in tiers if t.get("notify", True)]
    tier_lines = "\n".join(f"{t.get('emoji', '📰')} {t['label']}" for t in active_tiers)
    send_telegram(
        token,
        chat_id,
        f"🛰 <b>{topic} — Alert Bot is live</b>\n\n"
        f"Checking {len(feeds)} feeds every {interval_min} minutes.\n\n"
        f"<b>Active alert tiers:</b>\n{tier_lines}",
    )

    # ── Main polling loop ─────────────────────────────────────────────────────
    while True:
        try:
            n = poll_feeds(
                feeds, tiers, topic, token, chat_id, seen, cooldowns, cooldown_hours
            )
            if n:
                log.info("%d alert(s) sent.", n)
            else:
                log.info("No new high-impact items.")
        except Exception as e:
            # Log but don't crash — keep running
            log.error("Unexpected error in poll loop: %s", e)

        time.sleep(interval_min * 60)


if __name__ == "__main__":
    main()
