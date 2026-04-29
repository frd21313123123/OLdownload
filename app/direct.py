from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass
from typing import Any, Iterable

from .config import YTDLP_BINARY
from .utils import is_spotify_url, spotify_oembed_query


DIRECT_LINK_TIMEOUT_SECONDS = 45
STREAM_CHUNK_SIZE = 1024 * 1024
_SAFE_FILENAME_RE = re.compile(r'[<>:"/\\|?*\x00-\x1f]+')


@dataclass(frozen=True)
class DirectMediaFormat:
    format_id: str
    ext: str
    label: str
    resolution: str
    height: int | None
    fps: float | None
    filesize: int | None
    tbr: float | None


@dataclass(frozen=True)
class DirectMediaInfo:
    title: str
    thumbnail: str | None
    duration: int | None
    formats: list[DirectMediaFormat]


@dataclass(frozen=True)
class DirectMediaLink:
    url: str


def inspect_direct_video(source_url: str) -> DirectMediaInfo:
    info = _extract_info(source_url)
    formats = _extract_direct_formats(info.get("formats") or [])
    title = _clean_title(str(info.get("title") or "video"))
    thumbnail = info.get("thumbnail") if isinstance(info.get("thumbnail"), str) else None
    duration = info.get("duration") if isinstance(info.get("duration"), int) else None
    return DirectMediaInfo(title=title, thumbnail=thumbnail, duration=duration, formats=formats)


def resolve_direct_video_link(source_url: str, fmt: str, quality: str | None) -> DirectMediaLink:
    media = inspect_direct_video(source_url)
    preferred = _choose_preferred_format(media.formats, fmt, quality)
    if not preferred:
        raise ValueError("No direct single-file video stream is available for this format/quality")
    return resolve_direct_video_link_by_id(source_url, preferred.format_id)


def resolve_direct_video_link_by_id(source_url: str, format_id: str) -> DirectMediaLink:
    info = _extract_info(source_url)
    for item in info.get("formats") or []:
        if str(item.get("format_id") or "") == format_id and _is_direct_video_format(item):
            url = item.get("url")
            if isinstance(url, str) and url.startswith(("http://", "https://")):
                return DirectMediaLink(url=url)
    raise ValueError("The selected direct format is no longer available")


def build_stream_command(source_url: str, format_id: str) -> list[str]:
    source = _resolve_source(source_url)
    return [
        YTDLP_BINARY,
        "--no-playlist",
        "--no-cache-dir",
        "--quiet",
        "--no-warnings",
        "-f",
        format_id,
        "-o",
        "-",
        source,
    ]


def safe_download_filename(title: str, ext: str) -> str:
    clean_title = _SAFE_FILENAME_RE.sub("", title).strip(" .") or "video"
    clean_ext = _SAFE_FILENAME_RE.sub("", ext).strip(". ") or "mp4"
    return f"{clean_title[:120]}.{clean_ext}"


def stream_process_stdout(process: subprocess.Popen[bytes]) -> Iterable[bytes]:
    try:
        if process.stdout is None:
            return
        while True:
            chunk = process.stdout.read(STREAM_CHUNK_SIZE)
            if not chunk:
                break
            yield chunk
    finally:
        if process.poll() is None:
            process.terminate()
        process.wait(timeout=10)


def _extract_info(source_url: str) -> dict[str, Any]:
    source = _resolve_source(source_url)
    command = [
        YTDLP_BINARY,
        "--dump-single-json",
        "--no-playlist",
        "--no-cache-dir",
        "--quiet",
        "--no-warnings",
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
        raise ValueError("Timed out while reading available formats") from exc

    if result.returncode != 0:
        raise ValueError("Could not read available formats for this link")
    try:
        parsed = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise ValueError("Could not read available formats for this link") from exc
    if not isinstance(parsed, dict):
        raise ValueError("Could not read available formats for this link")
    return parsed


def _resolve_source(source_url: str) -> str:
    if not is_spotify_url(source_url):
        return source_url
    fallback_query = spotify_oembed_query(source_url)
    if not fallback_query:
        raise ValueError("Could not resolve Spotify metadata")
    return f"ytsearch1:{fallback_query}"


def _extract_direct_formats(formats: list[dict[str, Any]]) -> list[DirectMediaFormat]:
    direct_formats = [_to_direct_format(item) for item in formats if _is_direct_video_format(item)]
    direct_formats = [item for item in direct_formats if item is not None]
    by_variant: dict[tuple[int | None, str, float | None], DirectMediaFormat] = {}
    for item in direct_formats:
        key = (item.height, item.ext, item.fps)
        current = by_variant.get(key)
        if not current or (item.tbr or 0) > (current.tbr or 0):
            by_variant[key] = item
    return sorted(by_variant.values(), key=lambda item: (item.height or 0, item.tbr or 0), reverse=True)


def _is_direct_video_format(item: dict[str, Any]) -> bool:
    protocol = str(item.get("protocol") or "").lower()
    if protocol not in {"http", "https"}:
        return False
    if not str(item.get("url") or "").startswith(("http://", "https://")):
        return False
    if str(item.get("vcodec") or "none") == "none":
        return False
    if str(item.get("acodec") or "none") == "none":
        return False
    return True


def _to_direct_format(item: dict[str, Any]) -> DirectMediaFormat | None:
    format_id = str(item.get("format_id") or "")
    ext = str(item.get("ext") or "mp4")
    if not format_id:
        return None
    width = _int_or_none(item.get("width"))
    height = _int_or_none(item.get("height"))
    fps = _float_or_none(item.get("fps"))
    filesize = _int_or_none(item.get("filesize")) or _int_or_none(item.get("filesize_approx"))
    tbr = _float_or_none(item.get("tbr"))
    resolution = _resolution_label(width, height)
    label_parts = [resolution, ext.upper()]
    if fps and fps > 30:
        label_parts.append(f"{int(fps)} FPS")
    if filesize:
        label_parts.append(_size_label(filesize))
    return DirectMediaFormat(
        format_id=format_id,
        ext=ext,
        label=" · ".join(label_parts),
        resolution=resolution,
        height=height,
        fps=fps,
        filesize=filesize,
        tbr=tbr,
    )


def _choose_preferred_format(formats: list[DirectMediaFormat], fmt: str, quality: str | None) -> DirectMediaFormat | None:
    candidates = [item for item in formats if item.ext == fmt]
    if not candidates:
        candidates = formats
    if quality and quality != "best":
        max_height = int(quality)
        below_limit = [item for item in candidates if item.height and item.height <= max_height]
        if below_limit:
            candidates = below_limit
    return candidates[0] if candidates else None


def _clean_title(title: str) -> str:
    return re.sub(r"\s+", " ", title).strip() or "video"


def _resolution_label(width: int | None, height: int | None) -> str:
    if height:
        return f"{height}p"
    if width:
        return f"{width}px"
    return "Video"


def _size_label(size: int) -> str:
    if size >= 1024 * 1024 * 1024:
        return f"{size / 1024 / 1024 / 1024:.1f} GB"
    return f"{size / 1024 / 1024:.0f} MB"


def _int_or_none(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _float_or_none(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
