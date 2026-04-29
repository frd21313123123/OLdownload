from __future__ import annotations

from pathlib import Path
from typing import Iterable, Optional
from urllib.parse import quote_plus, urlparse

import requests

from .config import ALLOWED_HOSTS, DEFAULT_AUDIO_QUALITY, DEFAULT_VIDEO_QUALITY


AUDIO_FORMATS = {"mp3", "m4a", "wav", "flac"}
VIDEO_FORMATS = {"mp4", "webm"}
VIDEO_QUALITIES = {"best", "1080", "720", "480", "360", "240", "144"}
KNOWN_EXTENSIONS = {"mp3", "m4a", "wav", "flac", "mp4", "webm"}


def normalize_url(url: str) -> str:
    url = (url or "").strip()
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        raise ValueError("URL must use https://")
    host = (parsed.hostname or "").lower()
    if not host:
        raise ValueError("Invalid URL")
    if host not in ALLOWED_HOSTS and not any(host == h or host.endswith("." + h) for h in ALLOWED_HOSTS):
        raise ValueError("Unsupported source")
    return url


def is_spotify_url(url: str) -> bool:
    host = (urlparse(url).hostname or "").lower()
    return "spotify" in host


def validate_mode_and_format(mode: str, fmt: str, quality: Optional[str]) -> tuple[str, Optional[str]]:
    fmt = fmt.lower().strip()
    if mode == "audio":
        if fmt not in AUDIO_FORMATS:
            raise ValueError("Audio supports mp3, m4a, wav, flac")
        if fmt in {"mp3", "m4a"}:
            quality = (quality or DEFAULT_AUDIO_QUALITY).strip()
            if not quality.isdigit():
                raise ValueError("Audio quality must be numeric, for example 192")
            quality_value = int(quality)
            if quality_value < 32 or quality_value > 320:
                raise ValueError("Audio quality must be 32-320")
            return fmt, str(quality_value)
        if quality:
            raise ValueError("Quality is not used for this audio format")
        return fmt, None

    if mode == "video":
        if fmt not in VIDEO_FORMATS:
            raise ValueError("Video supports mp4, webm")
        quality = (quality or DEFAULT_VIDEO_QUALITY).strip().lower()
        if quality not in VIDEO_QUALITIES:
            raise ValueError("Video quality supports best, 1080, 720, 480, 360, 240, 144")
        return fmt, quality

    raise ValueError("Unsupported mode")


def choose_output_file(job_id: str, work_dir: Path, expected_format: str, fallback: Iterable[str]) -> Optional[Path]:
    candidates = sorted(work_dir.glob(f"{job_id}.*"), key=lambda p: p.stat().st_mtime, reverse=True)
    if candidates:
        for candidate in candidates:
            ext = candidate.suffix.lower().lstrip(".")
            if ext == expected_format:
                return candidate
            if ext in {"part", "fpart", "ytdl"}:
                continue
        return candidates[0]

    for pattern in fallback:
        files = sorted(work_dir.glob(pattern), key=lambda p: p.stat().st_mtime, reverse=True)
        if files:
            return files[0]
    return None


def spotify_oembed_query(url: str) -> Optional[str]:
    encoded = quote_plus(url)
    endpoint = f"https://open.spotify.com/oembed?url={encoded}"
    try:
        response = requests.get(endpoint, timeout=10)
        if response.status_code != 200:
            return None
        data = response.json()
    except Exception:
        return None

    title = (data.get("title") or "").strip()
    artist = (data.get("author_name") or "").strip()
    if not title:
        return None
    if artist:
        return f"{artist} - {title}"
    return title
