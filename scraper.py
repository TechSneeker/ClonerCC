"""
scraper.py
Scrapes all video URLs (+ descriptions) from a TikTok profile using exported
browser cookies. New videos are saved to the SQLite database; already-known
URLs are skipped so incremental cloning works correctly.

HOW TO EXPORT YOUR COOKIES:
  1. Install the "Cookie-Editor" extension in Chrome:
     https://chrome.google.com/webstore/detail/cookie-editor/hlkenndednhfkekhgcdicdfddnkalmdm
  2. Log into TikTok in Chrome.
  3. Go to https://www.tiktok.com, click the Cookie-Editor icon.
  4. Click "Export" → "Export as JSON".
  5. Save the file as cookies.json in this project folder.

Usage:
    python scraper.py dakpsico1
    python scraper.py dakpsico1 --max 50
    python scraper.py dakpsico1 --max 50 --download --output downloads
    python scraper.py dakpsico1 --cookies my_cookies.json
"""

import argparse
import json
import time
import sys
from datetime import datetime
from pathlib import Path

from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout
from playwright_stealth import stealth_sync

from db import VideoRecord, get_db

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------
DEFAULT_COOKIES_FILE = "cookies.json"
SCROLL_STEP  = 1200   # pixels per scroll — smaller step = more overlap, fewer missed cards
SCROLL_PAUSE = 2.5    # seconds to wait after each scroll for lazy-loaded cards to render
RENDER_WAIT  = 1.0    # extra wait before collecting anchors, letting the DOM settle

# Captcha selectors — TikTok uses these elements when showing a challenge
CAPTCHA_SELECTORS = [
    "#captcha-verify-image",
    "[class*='captcha']",
    "[id*='captcha']",
    "[class*='verify']",
    "iframe[src*='captcha']",
]


# ---------------------------------------------------------------------------
# Logging helpers
# ---------------------------------------------------------------------------
def log(msg: str, level: str = "INFO") -> None:
    ts     = datetime.now().strftime("%H:%M:%S")
    prefix = {"INFO": "·", "OK": "✔", "WARN": "!", "ERROR": "✖", "STEP": "▶"}.get(level, "·")
    print(f"[{ts}] {prefix} {msg}", flush=True)


# ---------------------------------------------------------------------------
# Cookie helpers
# ---------------------------------------------------------------------------
def _captcha_detected(page) -> bool:
    """Check if any known captcha element is visible on the page."""
    for selector in CAPTCHA_SELECTORS:
        try:
            el = page.query_selector(selector)
            if el and el.is_visible():
                return True
        except Exception:
            pass
    return False


def _wait_for_captcha_solve(page) -> None:
    """
    Pause scrolling and wait for the user to solve the captcha.
    Shows a tkinter dialog so the user knows to switch to the browser window.
    """
    import tkinter as tk
    from tkinter import messagebox

    log("⚠ CAPTCHA detectado! Resolva no browser e clique OK.", "WARN")

    # Bring up a small dialog on top
    root = tk.Tk()
    root.withdraw()
    root.attributes("-topmost", True)
    messagebox.showinfo(
        "ClonerCC — Captcha",
        "O TikTok exibiu um captcha.\n\n"
        "1. Alterne para a janela do browser\n"
        "2. Resolva o desafio\n"
        "3. Clique OK aqui para continuar o scroll",
        parent=root,
    )
    root.destroy()

    # Wait a bit for the page to recover after solving
    time.sleep(2)
    log("Continuando scroll após captcha.", "OK")


# ---------------------------------------------------------------------------
# Cookie helpers
# ---------------------------------------------------------------------------
def load_cookies(cookies_path: str) -> list[dict]:
    """Load cookies from a JSON file exported by Cookie-Editor."""
    path = Path(cookies_path)
    if not path.exists():
        log(f"Cookie file not found: {path.resolve()}", "ERROR")
        log("Export your TikTok cookies via the Cookie-Editor extension and save as cookies.json", "WARN")
        sys.exit(1)

    raw = json.loads(path.read_text(encoding="utf-8"))
    log(f"Loaded {len(raw)} cookies from {path.name}", "OK")
    return raw


def to_playwright_cookies(raw: list[dict]) -> list[dict]:
    """
    Normalize cookies exported by Cookie-Editor to the format Playwright expects.
    Cookie-Editor uses camelCase; Playwright needs specific keys.
    """
    pw_cookies = []
    for c in raw:
        cookie: dict = {
            "name"   : c.get("name", ""),
            "value"  : c.get("value", ""),
            "domain" : c.get("domain", ""),
            "path"   : c.get("path", "/"),
            "secure" : c.get("secure", False),
            "httpOnly": c.get("httpOnly", False),
        }
        # sameSite must be one of: "Strict", "Lax", "None"
        same_site = c.get("sameSite", "None")
        if same_site not in ("Strict", "Lax", "None"):
            same_site = "None"
        cookie["sameSite"] = same_site

        # expiry → expires (Unix timestamp as float)
        expiry = c.get("expirationDate") or c.get("expiry")
        if expiry:
            cookie["expires"] = float(expiry)

        pw_cookies.append(cookie)
    return pw_cookies


# ---------------------------------------------------------------------------
# Scraper
# ---------------------------------------------------------------------------
def scrape_profile(
    username: str,
    cookies_path: str = DEFAULT_COOKIES_FILE,
    max_videos: int | None = None,
) -> list[VideoRecord]:
    """
    Navigate to a TikTok profile, inject cookies, scroll, and collect video
    URLs + descriptions. Saves results to the SQLite database and skips URLs
    that were already scraped before.

    Args:
        username    : TikTok handle with or without '@'.
        cookies_path: Path to the JSON cookie file exported by Cookie-Editor.
        max_videos  : Stop after collecting this many *new* URLs (None = all).

    Returns:
        List of VideoRecord for videos that are NEW (not previously seen).
        Already-known videos are updated in the DB but not returned.
    """
    handle      = username.lstrip("@")
    profile_url = f"https://www.tiktok.com/@{handle}"
    db          = get_db()

    log(f"Profile    : {profile_url}", "STEP")
    log(f"Max videos : {max_videos or 'all'}")
    log(f"Cookies    : {cookies_path}")
    print()

    # ── Step 1: load cookies ────────────────────────────────────────────────
    log("Loading cookies...", "STEP")
    raw_cookies = load_cookies(cookies_path)
    pw_cookies  = to_playwright_cookies(raw_cookies)

    # URLs already known in the DB for this profile
    known_urls = db.get_known_urls(handle)
    log(f"Already in DB: {len(known_urls)} videos for @{handle}")

    # url → description map collected this session
    collected: dict[str, str] = {}   # {url: description}

    with sync_playwright() as p:

        browser = None
        context = None

        try:
            # ── Step 2: launch Chromium ───────────────────────────────────────
            log("Launching Chromium (headless + stealth)...", "STEP")
            browser = p.chromium.launch(
                headless=False,   # must be visible so user can solve captcha if needed
                args=["--disable-blink-features=AutomationControlled"],
            )
            context = browser.new_context(
                viewport={"width": 1280, "height": 900},
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/125.0.0.0 Safari/537.36"
                ),
            )
            log("Browser launched.", "OK")

            # ── Step 3: inject cookies ────────────────────────────────────────
            log(f"Injecting {len(pw_cookies)} cookies into browser context...", "STEP")
            context.add_cookies(pw_cookies)
            log("Cookies injected.", "OK")

            # ── Step 4: open page + apply stealth ─────────────────────────────
            page = context.new_page()
            stealth_sync(page)
            log("Stealth patches applied.", "OK")

            # ── Step 5: navigate ──────────────────────────────────────────────
            log(f"Navigating to {profile_url} ...", "STEP")
            page.goto(profile_url, wait_until="domcontentloaded", timeout=30_000)
            log("DOM content loaded.", "OK")

            # ── Step 6: wait for video cards ──────────────────────────────────
            log("Waiting for video cards to appear...", "STEP")
            try:
                page.wait_for_selector('a[href*="/video/"]', timeout=15_000)
                log("Video cards detected.", "OK")
            except PWTimeout:
                log("No video links found after 15s.", "ERROR")
                log("Possible causes: cookies expired, profile is private, or TikTok blocked the request.", "WARN")
                return []

            # ── Step 7: scroll loop ───────────────────────────────────────────
            log("Starting scroll loop...", "STEP")
            print()

            scroll_n       = 0
            previous_count = 0
            stale_rounds   = 0

            while True:
                scroll_n += 1

                # Extract url + description from each video card
                cards = page.eval_on_selector_all(
                    'a[href*="/video/"]',
                    """els => els.map(e => ({
                        url: e.href,
                        desc: (
                            e.querySelector('[data-e2e="video-desc"]') ||
                            e.querySelector('span[class*="desc"]') ||
                            e.closest('div[class*="item"]')?.querySelector('span') ||
                            null
                        )?.innerText?.trim() || ''
                    }))"""
                )

                new_this_round = 0
                for card in cards:
                    url  = card["url"]
                    desc = card["desc"]
                    if f"/@{handle}/video/" in url and url not in collected:
                        collected[url] = desc
                        new_this_round += 1

                count = len(collected)
                log(
                    f"Scroll #{scroll_n:>3}  —  "
                    f"total: {count:>4}  "
                    f"(+{new_this_round} new)"
                )

                # Stop at max_videos *new* (not already in DB)
                new_to_db = [u for u in collected if u not in known_urls]
                if max_videos and len(new_to_db) >= max_videos:
                    log(f"Reached limit of {max_videos} new videos. Stopping.", "OK")
                    break

                if count == previous_count:
                    stale_rounds += 1
                    if stale_rounds >= 3:
                        log(f"No new videos for {stale_rounds} scrolls in a row. End of profile.", "OK")
                        break
                    log(f"No new videos this scroll ({stale_rounds}/3 before stop).", "WARN")
                else:
                    stale_rounds = 0

                previous_count = count

                page.evaluate(f"window.scrollBy(0, {SCROLL_STEP})")
                time.sleep(SCROLL_PAUSE)

                # Check for captcha before collecting next batch
                if _captcha_detected(page):
                    _wait_for_captcha_solve(page)

                # Extra settle wait — lets lazy-loaded cards finish rendering
                # before the next collection pass
                try:
                    page.wait_for_load_state("networkidle", timeout=3_000)
                except Exception:
                    time.sleep(RENDER_WAIT)

        except KeyboardInterrupt:
            log("Interrupted by user.", "WARN")

        except Exception as e:
            log(f"Unexpected error: {e}", "ERROR")

        finally:
            print()
            log("Closing browser...", "STEP")
            try:
                if context:
                    context.close()
                if browser:
                    browser.close()
                log("Browser closed.", "OK")
            except Exception:
                pass

    # ── Step 8: persist to DB ─────────────────────────────────────────────
    print()
    log("Saving to database...", "STEP")
    new_records: list[VideoRecord] = []

    for url, desc in collected.items():
        record = VideoRecord(url=url, profile=handle, description=desc)
        db.upsert_video(record)
        if url not in known_urls:
            new_records.append(record)

    # Respect max_videos cap on what we return
    if max_videos:
        new_records = new_records[:max_videos]

    s = db.stats(handle)
    log(f"DB stats for @{handle} — pending: {s.get('pending', 0)}  downloaded: {s.get('downloaded', 0)}  error: {s.get('error', 0)}", "OK")
    log(f"New videos this run: {len(new_records)}", "OK")

    # ── Step 9: fetch descriptions via yt-dlp (no download) ───────────────
    if new_records:
        log("Fetching descriptions via yt-dlp...", "STEP")
        from downloader import fetch_descriptions
        fetch_descriptions(new_records, cookies_path=cookies_path)

    return new_records


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def main() -> None:
    parser = argparse.ArgumentParser(
        description="Scrape TikTok video URLs from a profile using exported cookies."
    )
    parser.add_argument(
        "username",
        nargs="?",
        default=None,
        help="TikTok handle (e.g. dakpsico1 or @dakpsico1)",
    )
    parser.add_argument(
        "--user", "-u",
        dest="username_flag",
        default=None,
        metavar="HANDLE",
        help="TikTok handle as a flag (alternative to positional arg)",
    )
    parser.add_argument(
        "--cookies", "-c",
        default=DEFAULT_COOKIES_FILE,
        metavar="FILE",
        help=f"Path to cookie JSON file (default: {DEFAULT_COOKIES_FILE})",
    )
    parser.add_argument(
        "--max",
        type=int,
        default=None,
        metavar="N",
        help="Maximum number of videos to collect (default: all)",
    )
    parser.add_argument(
        "--download",
        action="store_true",
        help="Download the collected videos after scraping",
    )
    parser.add_argument(
        "--output",
        default="downloads",
        metavar="DIR",
        help="Output directory for downloaded videos (default: downloads)",
    )

    args     = parser.parse_args()
    username = args.username or args.username_flag
    if not username:
        parser.error("username is required (positional or via --user)")

    records = scrape_profile(username, cookies_path=args.cookies, max_videos=args.max)

    if not records:
        log("No new URLs collected. Exiting.", "ERROR")
        sys.exit(1)

    print()
    log(f"New videos ({len(records)}):", "STEP")
    for i, r in enumerate(records, 1):
        desc_preview = r.description[:60] + "…" if len(r.description) > 60 else r.description
        print(f"  {i:>3}. {r.url}")
        if desc_preview:
            print(f"       └─ {desc_preview}")

    if args.download:
        from downloader import download_records
        print()
        log(f"Starting download → '{args.output}'", "STEP")
        download_records(records, args.output)


if __name__ == "__main__":
    main()
