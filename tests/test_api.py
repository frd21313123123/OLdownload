from datetime import datetime, timedelta, timezone
import uuid

from fastapi.testclient import TestClient

import app.main as main
from app.config import DOWNLOAD_DIR, JOB_TTL_SECONDS
from app.direct import DirectMediaFormat, DirectMediaInfo, DirectMediaLink
from app.main import app
from app.manager import _JobState
from app.schemas import DownloadJob, DownloadMode, JobStatus


client = TestClient(app)


def test_health():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_reject_bad_source():
    response = client.post(
        "/api/download",
        json={"url": "https://example.com/some-video", "mode": "audio", "format": "mp3", "quality": "192"},
    )
    assert response.status_code == 400


def test_reject_bad_format():
    response = client.post(
        "/api/download",
        json={"url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ", "mode": "video", "format": "avi", "quality": "720"},
    )
    assert response.status_code == 400


def test_create_direct_video_link(monkeypatch):
    def fake_resolve(url: str, format_id: str):
        assert url == "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
        assert format_id == "22"
        return DirectMediaLink(url="https://media.example/video.mp4")

    monkeypatch.setattr(main, "resolve_direct_video_link_by_id", fake_resolve)

    response = client.post(
        "/api/direct-link",
        json={"url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ", "format_id": "22"},
    )

    assert response.status_code == 200
    assert response.json() == {"url": "https://media.example/video.mp4"}


def test_list_direct_formats(monkeypatch):
    def fake_inspect(url: str):
        assert url == "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
        return DirectMediaInfo(
            title="Example",
            thumbnail="https://img.example/thumb.jpg",
            duration=95,
            formats=[
                DirectMediaFormat(
                    format_id="22",
                    ext="mp4",
                    label="720p · MP4",
                    resolution="720p",
                    height=720,
                    fps=30,
                    filesize=123,
                    tbr=1000,
                )
            ],
        )

    monkeypatch.setattr(main, "inspect_direct_video", fake_inspect)

    response = client.post(
        "/api/formats",
        json={"url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ"},
    )

    assert response.status_code == 200
    assert response.json()["title"] == "Example"
    assert response.json()["formats"][0]["format_id"] == "22"


def test_downloaded_server_file_is_removed_after_response():
    job_id = uuid.uuid4().hex
    work_dir = DOWNLOAD_DIR / job_id
    work_dir.mkdir(parents=True, exist_ok=True)
    file_path = work_dir / f"{job_id}.mp4"
    file_path.write_bytes(b"video")
    now = datetime.now(timezone.utc)
    job = DownloadJob(
        id=job_id,
        url="https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        mode=DownloadMode.video,
        format="mp4",
        quality="best",
        status=JobStatus.done,
        progress=100,
        created_at=now,
        updated_at=now,
        completed_at=now,
        file_name=file_path.name,
        file_size=5,
    )
    with main.manager._lock:
        main.manager._jobs[job_id] = _JobState(job=job)

    response = client.get(f"/api/download/{job_id}")

    assert response.status_code == 200
    assert response.content == b"video"
    assert not work_dir.exists()
    assert main.manager.get_job(job_id) is None


def test_completed_server_file_expires_after_ttl():
    job_id = uuid.uuid4().hex
    work_dir = DOWNLOAD_DIR / job_id
    work_dir.mkdir(parents=True, exist_ok=True)
    file_path = work_dir / f"{job_id}.mp4"
    file_path.write_bytes(b"video")
    now = datetime.now(timezone.utc)
    completed_at = now - timedelta(seconds=JOB_TTL_SECONDS + 1)
    job = DownloadJob(
        id=job_id,
        url="https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        mode=DownloadMode.video,
        format="mp4",
        quality="best",
        status=JobStatus.done,
        progress=100,
        created_at=completed_at,
        updated_at=completed_at,
        completed_at=completed_at,
        file_name=file_path.name,
        file_size=5,
    )
    with main.manager._lock:
        main.manager._jobs[job_id] = _JobState(job=job)

    main.manager.cleanup_expired_jobs()

    assert not work_dir.exists()
    assert main.manager.get_job(job_id) is None
