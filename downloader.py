"""
downloader.py
Downloads videos from a list of URLs using yt-dlp.
"""

import yt_dlp
import os
from pathlib import Path


def build_ydl_options(output_dir: str) -> dict:
    """Build yt-dlp options for downloading."""
    output_template = str(Path(output_dir) / "%(uploader)s_%(id)s.%(ext)s")

    return {
        # Output template: saves as <uploader>_<video_id>.<ext> inside output_dir
        "outtmpl": output_template,

        # Prefer best single-file format (no merge required)
        "format": "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",

        # Merge output into mp4 when separate streams are downloaded
        "merge_output_format": "mp4",

        # Retry settings
        "retries": 3,
        "fragment_retries": 3,

        # Show progress in terminal
        "progress": True,

        # Avoid re-downloading already downloaded files
        "nooverwrites": True,

        # Skip unavailable videos without stopping the whole batch
        "ignoreerrors": True,
    }


def download_videos(urls: list[str], output_dir: str) -> None:
    """
    Download a list of video URLs to the specified output directory.

    Args:
        urls: List of video URLs to download.
        output_dir: Path to the folder where videos will be saved.
    """
    if not urls:
        print("No URLs provided.")
        return

    # Ensure the output directory exists
    Path(output_dir).mkdir(parents=True, exist_ok=True)

    print(f"Output directory : {os.path.abspath(output_dir)}")
    print(f"Videos to download: {len(urls)}\n")

    ydl_opts = build_ydl_options(output_dir)

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        results = ydl.download(urls)

    print(f"\nDownload finished. yt-dlp exit code: {results}")


# ---------------------------------------------------------------------------
# Example / entry point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    URLS = [
        "https://www.tiktok.com/@dakpsico1/video/7570365422873169159",
        "https://www.tiktok.com/@dakpsico1/video/7660343642267127060",
    ]

    OUTPUT_DIR = "downloads"

    download_videos(URLS, OUTPUT_DIR)
