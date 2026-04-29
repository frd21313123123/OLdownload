from __future__ import annotations

import subprocess
from dataclasses import dataclass

from .config import YTDLP_BINARY
from .utils import is_spotify_url, spotify_oembed_query


DIRECT_LINK_TIMEOUT_SECONDS = 45


@dataclass(frozen=True)
class DirectMediaLink:
    url: str


def resolve_direct_video_link(source_url: str, fmt: str, quality: str | None) -> DirectMediaLink:
    sources = [source_url]
    if is_spotify_url(source_url):
        fallback_query = spotify_oembed_query(source_url)
        if fallback_query:
            sources.append(f"ytsearch1:{fallback_query}")

    last_error = "Could not prepare a direct media link"
    for source in dict.fromkeys(sources):
        try:
            return _resolve_with_ytdlp(source, fmt, quality)
        except ValueError as exc:
            last_error = str(exc)

    raise ValueError(last_error)


def _resolve_with_ytdlp(source: str, fmt: str, quality: str | None) -> DirectMediaLink:
    last_error = "No direct single-file video stream is available for this format/quality"
    for selector in _single_file_format_selectors(fmt, quality):
        command = [
            YTDLP_BINARY,
            "--no-playlist",
            "--no-warnings",
            "--get-url",
            "-f",
            selector,
            source,
        ]

        try:
            result = subprocess.run(
                command,
                check=False,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=DIRECT_LINK_TIMEOUT_SECONDS,
            )
        except FileNotFoundError as exc:
            raise ValueError("yt-dlp is not installed or not available in PATH") from exc
        except subprocess.TimeoutExpired as exc:
            raise ValueError("Timed out while preparing a direct media link") from exc

        if result.returncode != 0:
            continue

        urls = [line.strip() for line in result.stdout.splitlines() if line.strip().startswith(("http://", "https://"))]
        if len(urls) == 1:
            return DirectMediaLink(url=urls[0])

    raise ValueError(last_error)


def _single_file_format_selectors(fmt: str, quality: str | None) -> list[str]:
    selectors = [_single_file_format_selector(fmt, quality)]
    if quality and quality != "best":
        selectors.append(_single_file_format_selector(fmt, None))
    selectors.append(_single_file_format_selector(None, quality))
    selectors.append(_single_file_format_selector(None, None))

    deduped = []
    for selector in selectors:
        if selector not in deduped:
            deduped.append(selector)
    return deduped


def _single_file_format_selector(fmt: str | None, quality: str | None) -> str:
    filters = ["vcodec!=none", "acodec!=none"]
    if fmt:
        filters.insert(0, f"ext={fmt}")
    if quality and quality != "best":
        filters.append(f"height<={quality}")

    filter_expr = "".join(f"[{item}]" for item in filters)
    return f"best{filter_expr}"
