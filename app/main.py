from __future__ import annotations

import uuid
from datetime import datetime, timezone
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .config import DOWNLOAD_DIR, STATIC_DIR
from .manager import DownloadManager
from .schemas import DownloadJob, DownloadMode, DownloadRequest, ErrorResponse, JobStatus, DownloadResponse
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
    )


@app.get("/")
def index():
    return FileResponse(STATIC_DIR / "index.html")
