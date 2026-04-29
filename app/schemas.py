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
    file_name: Optional[str] = None
    file_size: Optional[int] = None
    error: Optional[str] = None
    visible: bool = True


class DownloadResponse(BaseModel):
    id: str
    status: JobStatus


class ErrorResponse(BaseModel):
    detail: str
