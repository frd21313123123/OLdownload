from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field, HttpUrl


class JobStatus(str, Enum):
    queued = "queued"
    downloading = "downloading"
    converting = "converting"
    done = "done"
    error = "error"
    cancelled = "cancelled"


class DownloadMode(str, Enum):
    audio = "audio"
    video = "video"


class DownloadRequest(BaseModel):
    url: HttpUrl
    mode: DownloadMode
    format: str = Field(min_length=1)
    quality: Optional[str] = Field(default=None, min_length=1, max_length=16)


class FormatRequest(BaseModel):
    url: HttpUrl


class DirectLinkRequest(BaseModel):
    url: HttpUrl
    format_id: str = Field(min_length=1, max_length=64)


class DownloadJob(BaseModel):
    id: str
    url: str
    mode: DownloadMode
    format: str
    quality: Optional[str]
    status: JobStatus
    progress: int = 0
    message: str = ""
    created_at: datetime
    updated_at: datetime
    completed_at: Optional[datetime] = None
    downloaded_at: Optional[datetime] = None
    file_name: Optional[str] = None
    file_size: Optional[int] = None
    error: Optional[str] = None
    visible: bool = True


class DownloadResponse(BaseModel):
    id: str
    status: JobStatus


class DirectDownloadResponse(BaseModel):
    url: str


class DirectFormat(BaseModel):
    format_id: str
    ext: str
    label: str
    resolution: str
    height: Optional[int] = None
    fps: Optional[float] = None
    filesize: Optional[int] = None
    tbr: Optional[float] = None


class FormatResponse(BaseModel):
    title: str
    thumbnail: Optional[str] = None
    duration: Optional[int] = None
    uploader: Optional[str] = None
    channel: Optional[str] = None
    upload_date: Optional[str] = None
    view_count: Optional[int] = None
    webpage_url: Optional[str] = None
    formats: list[DirectFormat]


class ErrorResponse(BaseModel):
    detail: str
