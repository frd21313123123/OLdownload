from __future__ import annotations

import uuid
import subprocess
from datetime import datetime, timezone
from contextlib import asynccontextmanager
from urllib.parse import quote

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from starlette.background import BackgroundTask

from .config import DOWNLOAD_DIR, STATIC_DIR
from .direct import build_stream_command, inspect_direct_video, resolve_direct_video_link_by_id, safe_download_filename, stream_process_stdout
from .manager import DownloadManager
from .schemas import DirectDownloadResponse, DirectFormat, DirectLinkRequest, DownloadJob, DownloadMode, DownloadRequest, ErrorResponse, FormatRequest, FormatResponse, JobStatus, DownloadResponse
from .utils import normalize_url, validate_mode_and_format

manager = DownloadManager()

@asynccontextmanager
async def lifespan(_app: FastAPI):
    try:
        yield
    finally:
        manager.shutdown()

app = FastAPI(title="Local Media Downloader", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:8000", "http://127.0.0.1:8000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/download", response_model=DownloadResponse, responses={400: {"model": ErrorResponse}})
def create_download(payload: DownloadRequest) -> DownloadResponse:
    try:
        normalized_url = normalize_url(str(payload.url))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    try:
        fmt, quality = validate_mode_and_format(payload.mode.value, payload.format, payload.quality)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    job_id = uuid.uuid4().hex
    now = datetime.now(timezone.utc)
    job = DownloadJob(
        id=job_id,
        url=normalized_url,
        mode=payload.mode,
        format=fmt,
        quality=quality,
        status=JobStatus.queued,
        created_at=now,
        updated_at=now,
    )
    manager.submit_job(job)
    return DownloadResponse(id=job_id, status=job.status)


@app.post("/api/formats", response_model=FormatResponse, responses={400: {"model": ErrorResponse}})
def list_direct_formats(payload: FormatRequest) -> FormatResponse:
    try:
        normalized_url = normalize_url(str(payload.url))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    try:
        media = inspect_direct_video(normalized_url)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return FormatResponse(
        title=media.title,
        thumbnail=media.thumbnail,
        duration=media.duration,
        formats=[DirectFormat(**item.__dict__) for item in media.formats],
    )


@app.post("/api/direct-link", response_model=DirectDownloadResponse, responses={400: {"model": ErrorResponse}})
def create_direct_link(payload: DirectLinkRequest) -> DirectDownloadResponse:
    try:
        normalized_url = normalize_url(str(payload.url))
        media = resolve_direct_video_link_by_id(normalized_url, payload.format_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return DirectDownloadResponse(url=media.url)


@app.get("/api/stream", responses={400: {"model": ErrorResponse}})
def stream_direct_file(url: str = Query(min_length=1), format_id: str = Query(min_length=1, max_length=64)):
    try:
        normalized_url = normalize_url(url)
        media = inspect_direct_video(normalized_url)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    selected = next((item for item in media.formats if item.format_id == format_id), None)
    if not selected:
        raise HTTPException(status_code=400, detail="The selected direct format is no longer available")

    try:
        process = subprocess.Popen(
            build_stream_command(normalized_url, format_id),
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )
    except FileNotFoundError:
        raise HTTPException(status_code=400, detail="yt-dlp is not installed or not available in PATH")

    filename = safe_download_filename(media.title, selected.ext)
    headers = {
        "Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}",
        "Cache-Control": "no-store",
    }
    return StreamingResponse(
        stream_process_stdout(process),
        media_type="application/octet-stream",
        headers=headers,
    )


@app.get("/api/jobs")
def list_jobs():
    return manager.list_jobs()


@app.get("/api/jobs/{job_id}", response_model=DownloadJob)
def get_job(job_id: str):
    job = manager.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job

@app.delete("/api/jobs/{job_id}", responses={404: {"model": ErrorResponse}})
def delete_job(job_id: str):
    if not manager.remove_job(job_id):
        raise HTTPException(status_code=404, detail="Job not found")
    return {"status": "ok"}


@app.get("/api/download/{job_id}")
def download_job_file(job_id: str):
    job = manager.get_job(job_id)
    if not job or not job.visible:
        raise HTTPException(status_code=404, detail="Job not found")
    if job.status != JobStatus.done:
        raise HTTPException(status_code=409, detail="Job is not ready")
    if not job.file_name:
        raise HTTPException(status_code=500, detail="File metadata missing")
    file_path = DOWNLOAD_DIR / job_id / job.file_name
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="Downloaded file is missing")
    return FileResponse(
        path=file_path,
        filename=job.file_name,
        media_type="application/octet-stream",
        background=BackgroundTask(manager.remove_completed_job, job_id),
    )


@app.get("/")
def index():
    return FileResponse(STATIC_DIR / "index.html")
