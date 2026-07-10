"""
scraper.py
Scrapes all video URLs from a TikTok profile using exported browser cookies.

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

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------
DEFAULT_COOKIES_FILE = "cookies.json"
SCROLL_STEP  = 2000
SCROLL_PAUSE = 2.0   # seconds between scrolls


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
) -> list[str]:
    """
    Navigate to a TikTok profile, inject cookies, scroll, and collect video URLs.

    Args:
        username    : TikTok handle with or without '@'.
        cookies_path: Path to the JSON cookie file exported by Cookie-Editor.
        max_videos  : Stop after this many URLs (None = collect all).

    Returns:
        Ordered list of unique video URLs.
    """
    handle      = username.lstrip("@")
    profile_url = f"https://www.tiktok.com/@{handle}"

    log(f"Profile    : {profile_url}", "STEP")
    log(f"Max videos : {max_videos or 'all'}")
    log(f"Cookies    : {cookies_path}")
    print()

    # ── Step 1: load cookies ────────────────────────────────────────────────
    log("Loading cookies...", "STEP")
    raw_cookies = load_cookies(cookies_path)
    pw_cookies  = to_playwright_cookies(raw_cookies)

    collected: list[str] = []

    with sync_playwright() as p:

        browser = None
        context = None

        try:
            # ── Step 2: launch Playwright's own Chromium (no lock issues) ────────
            log("Launching Chromium (headless + stealth)...", "STEP")
            browser = p.chromium.launch(
                headless=True,
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

            # ── Step 3: inject cookies ───────────────────────────────────────────
            log(f"Injecting {len(pw_cookies)} cookies into browser context...", "STEP")
            context.add_cookies(pw_cookies)
            log("Cookies injected.", "OK")

            # ── Step 4: open page + apply stealth ────────────────────────────────
            page = context.new_page()
            stealth_sync(page)
            log("Stealth patches applied.", "OK")

            # ── Step 5: navigate ─────────────────────────────────────────────────
            log(f"Navigating to {profile_url} ...", "STEP")
            page.goto(profile_url, wait_until="domcontentloaded", timeout=30_000)
            log("DOM content loaded.", "OK")

        # ── Step 6: wait for video cards ─────────────────────────────────────
            log("Waiting for video cards to appear...", "STEP")
            try:
                page.wait_for_selector('a[href*="/video/"]', timeout=15_000)
                log("Video cards detected.", "OK")
            except PWTimeout:
                log("No video links found after 15s.", "ERROR")
                log("Possible causes: cookies expired, profile is private, or TikTok blocked the request.", "WARN")
                return []

            # ── Step 7: scroll loop ───────────────────────────────────────────────
            log("Starting scroll loop...", "STEP")
            print()

            scroll_n       = 0
            previous_count = 0
            stale_rounds   = 0

            while True:
                scroll_n += 1

                anchors = page.eval_on_selector_all(
                    'a[href*="/video/"]',
                    "els => els.map(e => e.href)"
                )

                seen           = set(collected)
                new_this_round = 0
                for url in anchors:
                    # Only keep videos that belong to the target profile
                    if f"/@{handle}/video/" in url and url not in seen:
                        collected.append(url)
                        seen.add(url)
                        new_this_round += 1

                count = len(collected)
                log(
                    f"Scroll #{scroll_n:>3}  —  "
                    f"total: {count:>4}  "
                    f"(+{new_this_round} new)"
                )

                if max_videos and count >= max_videos:
                    collected = collected[:max_videos]
                    log(f"Reached limit of {max_videos} videos. Stopping.", "OK")
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

        except KeyboardInterrupt:
            log("Interrupted by user.", "WARN")

        except Exception as e:
            log(f"Unexpected error: {e}", "ERROR")

        finally:
            # ── Step 8: guaranteed browser cleanup ───────────────────────────
            print()
            log("Closing browser...", "STEP")
            try:
                if context:
                    context.close()
                if browser:
                    browser.close()
                log("Browser closed.", "OK")
            except Exception:
                # If already closed, ignore
                pass

    print()
    log(f"Done. Total URLs collected: {len(collected)}", "OK")
    return collected


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

    urls = scrape_profile(username, cookies_path=args.cookies, max_videos=args.max)

    if not urls:
        log("No URLs collected. Exiting.", "ERROR")
        sys.exit(1)

    print()
    log(f"Collected URLs ({len(urls)}):", "STEP")
    for i, url in enumerate(urls, 1):
        print(f"  {i:>3}. {url}")

    if args.download:
        from downloader import download_videos
        print()
        log(f"Starting download → '{args.output}'", "STEP")
        download_videos(urls, args.output)


if __name__ == "__main__":
    main()
