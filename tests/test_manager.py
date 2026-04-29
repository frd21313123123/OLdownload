from datetime import datetime, timezone
import threading

from app.manager import DownloadManager, _JobState
from app.schemas import DownloadJob, DownloadMode, JobStatus


def _job() -> DownloadJob:
    now = datetime.now(timezone.utc)
    return DownloadJob(
        id="test-job",
        url="https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        mode=DownloadMode.video,
        format="mp4",
        quality="best",
        status=JobStatus.downloading,
        created_at=now,
        updated_at=now,
    )


def test_intermediate_100_percent_is_not_reported_as_done():
    manager = object.__new__(DownloadManager)
    manager._lock = threading.Lock()
    state = _JobState(job=_job())

    manager._handle_progress_line(state, "[download] 100% of 102.28MiB in 00:00:11 at 1.05MiB/s")

    assert state.job.status == JobStatus.downloading
    assert state.job.progress == 99
    assert state.job.message == "Скачиваю части файла"


def test_merger_line_switches_to_converting():
    manager = object.__new__(DownloadManager)
    manager._lock = threading.Lock()
    state = _JobState(job=_job())

    manager._handle_progress_line(state, '[Merger] Merging formats into "test-job.mp4"')

    assert state.job.status == JobStatus.converting
    assert state.job.message == "Склеиваю видео и звук"
