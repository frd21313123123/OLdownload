from __future__ import annotations

from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent.parent
DOWNLOAD_DIR = BASE_DIR / "downloads"
STATIC_DIR = BASE_DIR / "app" / "static"
ALLOWED_HOSTS = {
    "youtube.com",
    "m.youtube.com",
    "www.youtube.com",
    "youtu.be",
    "music.youtube.com",
    "twitter.com",
    "www.twitter.com",
    "x.com",
    "www.x.com",
    "open.spotify.com",
    "www.spotify.com",
    "spotify.com",
}

JOB_TTL_SECONDS = 3600 * 12
MAX_CONCURRENT_DOWNLOADS = 2
CLEANUP_INTERVAL_SECONDS = 60
YTDLP_BINARY = "yt-dlp"
DEFAULT_AUDIO_QUALITY = "192"
DEFAULT_VIDEO_QUALITY = "best"
