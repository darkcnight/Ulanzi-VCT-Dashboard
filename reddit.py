"""
Reddit module — configurable subreddits (default: r/ValorantCompetitive).
Fetches posts with configurable upvote threshold from the past N hours.
All tunables read from state.cfg at call time.
Suppressed during live Valorant matches.
"""

import re
import httpx
import logging
import time
from datetime import datetime

import state

logger = logging.getLogger(__name__)

APP_NAME = "reddit_valorant"

_HEADERS = {
    "User-Agent": "UlanziClock/1.0 (personal NAS dashboard; no ads)",
}

# ── Module state ──────────────────────────────────────────────────────────────

_last_fetch: datetime = datetime.min
_cached_text: str | None = None


# ── Config helpers ────────────────────────────────────────────────────────────

def _rcfg() -> dict:
    return state.cfg.get("reddit", {})

def _poll_interval() -> int:
    return int(_rcfg().get("poll_interval_seconds", 1200))

def _min_score() -> int:
    return int(_rcfg().get("min_score", 300))

def _max_age_secs() -> int:
    return int(_rcfg().get("max_age_hours", 24)) * 3600

def _max_posts() -> int:
    return int(_rcfg().get("max_posts", 3))

def _hot_url() -> str:
    subs = _rcfg().get("subreddits", ["ValorantCompetitive"])
    joined = "+".join(s.strip() for s in subs if s.strip())
    return f"https://www.reddit.com/r/{joined}/hot.json?limit=50&raw_json=1"


# ── Match-thread filter ───────────────────────────────────────────────────────

_MATCH_THREAD_RE = re.compile(r'post.?match|match thread', re.IGNORECASE)

def _is_match_thread(d: dict) -> bool:
    return bool(
        _MATCH_THREAD_RE.search(d.get("title", ""))
        or _MATCH_THREAD_RE.search(d.get("link_flair_text") or "")
    )


# ── Config helpers (continued) ────────────────────────────────────────────────

def _comments_per_post() -> int:
    return int(_rcfg().get("comments_per_post", 3))


# ── Comment fetch ─────────────────────────────────────────────────────────────

# Matches comments that are purely a bare URL, markdown image, or markdown link
_LINK_ONLY_RE = re.compile(
    r'^\s*(?:!?\[.*?\]\s*\(.*?\)|https?://\S+)\s*$',
    re.IGNORECASE | re.DOTALL,
)

def _is_text_comment(body: str) -> bool:
    """Return True if the comment has readable text content (not just a link/image)."""
    return len(body.strip()) > 15 and not _LINK_ONLY_RE.match(body)


_INLINE_URL_RE = re.compile(r'https?://\S+', re.IGNORECASE)

def _clean_comment(body: str) -> str:
    """Strip inline URLs and tidy whitespace from a comment body."""
    body = _INLINE_URL_RE.sub('', body)
    return re.sub(r'\s+', ' ', body).strip()


def _fetch_comments(post_id: str, subreddit: str) -> list[str]:
    """Return up to comments_per_post text-only top-level comment bodies, by score.
    Fetches 30 candidates so image/gif-only comments can be skipped freely.
    Inline URLs are stripped from comment bodies before display.
    """
    n = _comments_per_post()
    if n == 0:
        return []

    url = f"https://www.reddit.com/r/{subreddit}/comments/{post_id}.json?limit=30&sort=top&raw_json=1"
    try:
        resp = httpx.get(url, headers=_HEADERS, timeout=10)
        resp.raise_for_status()
        listing = resp.json()
        children = listing[1]["data"]["children"]
    except Exception as e:
        logger.warning(f"[reddit] comments fetch failed for {post_id}: {e}")
        return []

    comments = []
    for child in children:
        if child.get("kind") != "t1":
            continue
        d = child.get("data", {})
        raw   = (d.get("body") or "").replace("\n", " ").strip()
        score = d.get("score", 0)
        if raw and raw not in ("[deleted]", "[removed]") and _is_text_comment(raw):
            body = _clean_comment(raw)
            if body:
                comments.append((score, body))

    comments.sort(key=lambda x: x[0], reverse=True)
    return [body[:120] + ("…" if len(body) > 120 else "") for _, body in comments[:n]]


# ── Internal helpers ──────────────────────────────────────────────────────────

def _fetch_posts() -> list[dict] | None:
    """Return a list of posts on success (possibly empty), None on fetch error."""
    try:
        resp = httpx.get(_hot_url(), headers=_HEADERS, timeout=10)
        resp.raise_for_status()
        children = resp.json()["data"]["children"]
    except Exception as e:
        logger.error(f"[reddit] posts fetch failed: {e}")
        return None

    cutoff = time.time() - _max_age_secs()
    min_s  = _min_score()
    posts  = []
    for child in children:
        d = child.get("data", {})
        if (
            d.get("score", 0) >= min_s
            and d.get("created_utc", 0) >= cutoff
            and not d.get("stickied", False)
            and not _is_match_thread(d)
        ):
            posts.append(d)

    logger.info(f"[reddit] {len(posts)} qualifying post(s) (of {len(children)} fetched)")
    posts = posts[:_max_posts()]

    subs = _rcfg().get("subreddits", ["ValorantCompetitive"])
    subreddit = "+".join(s.strip() for s in subs if s.strip())
    for post in posts:
        post["_top_comments"] = _fetch_comments(post["id"], subreddit)

    return posts


def _build_text(posts: list[dict]) -> str:
    blocks = []
    for post in posts:
        title = post.get("title", "").strip()
        score = post.get("score", 0)
        if len(title) > 80:
            title = title[:77] + "..."
        parts = [f"[{score}↑] {title}"]
        for comment in post.get("_top_comments", []):
            parts.append(f"↳ {comment}")
        blocks.append("   |   ".join(parts))
    return "   ·····   ".join(blocks) if blocks else ""


def _push(awtrix, text: str) -> None:
    scroll_spd, dur = state.scroll_params_for_text(text)
    payload = {
        "text": text,
        "color": state.get_app_color(APP_NAME),
        "scrollSpeed": scroll_spd,
        "lifetime": _poll_interval(),
        "duration": dur,
        "repeat": 1,
    }
    try:
        resp = awtrix.push_app(APP_NAME, payload)
        preview = text[:120] + ("…" if len(text) > 120 else "")
        state.active_apps[APP_NAME] = {
            "text":      preview,
            "full_text": text if len(text) > 120 else None,
            "color":     state.get_app_color(APP_NAME),
            "last_updated": datetime.now().strftime("%H:%M:%S"),
        }
        logger.info(f"[reddit] pushed {len(text)} chars → HTTP {resp.status_code}")
    except Exception as e:
        logger.error(f"[reddit] push failed: {e}")


# ── Public interface ──────────────────────────────────────────────────────────

def tick(awtrix, is_live: bool) -> None:
    global _last_fetch, _cached_text

    now = datetime.now()
    due = (now - _last_fetch).total_seconds() >= _poll_interval()

    if due:
        posts = _fetch_posts()  # None=error, []=genuinely empty, [...]= content
        _last_fetch = now

        if posts is None:
            # Fetch error — keep existing cache unchanged, don't update device
            logger.warning("[reddit] keeping stale cache due to fetch error")
        elif posts:
            _cached_text = _build_text(posts)
            preview = _cached_text[:120] + ("…" if len(_cached_text) > 120 else "")
            state.active_apps[APP_NAME] = {
                "text":         preview,
                "full_text":    _cached_text if len(_cached_text) > 120 else None,
                "color":        state.get_app_color(APP_NAME),
                "last_updated": datetime.now().strftime("%H:%M:%S"),
            }
        else:
            # Successful fetch but nothing qualifies — clear cache and device
            _cached_text = ""
            state.active_apps.pop(APP_NAME, None)
            try:
                awtrix.delete_app(APP_NAME)
            except Exception:
                pass
            logger.info("[reddit] no qualifying posts — cleared app")

    if is_live:
        return  # suppressed — data cached for when match ends

    if _cached_text and state.modules.get(APP_NAME, True) and due:
        _push(awtrix, _cached_text)


def force_refresh() -> None:
    global _last_fetch
    _last_fetch = datetime.min


def clear(awtrix) -> None:
    try:
        awtrix.delete_app(APP_NAME)
        state.active_apps.pop(APP_NAME, None)
        logger.info("[reddit] cleared app")
    except Exception as e:
        logger.error(f"[reddit] clear failed: {e}")


def restore(awtrix) -> None:
    if _cached_text and state.modules.get(APP_NAME, True):
        _push(awtrix, _cached_text)
        logger.info("[reddit] restored from cache")
