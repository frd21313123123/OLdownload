from __future__ import annotations

import queue
import re
import shutil
import subprocess
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Optional

from .config import CLEANUP_INTERVAL_SECONDS, DOWNLOAD_DIR, JOB_TTL_SECONDS, MAX_CONCURRENT_DOWNLOADS, YTDLP_BINARY
from .schemas import DownloadJob, DownloadMode, JobStatus
from .utils import KNOWN_EXTENSIONS, choose_output_file, is_spotify_url, spotify_oembed_query


_PROGRESS_RE = re.compile(r"\[download\]\s+(\d+(?:\.\d+)?)%")
_PROCESSING_MARKERS = (
    "[Merger]",
    "[ExtractAudio]",
    "[VideoConvertor]",
    "[Fixup",
    "[MoveFiles]",
    "Merging formats",
    "Deleting original file",
)


@dataclass
class _JobState:
    job: DownloadJob
    process: Optional[subprocess.Popen] = None


class DownloadManager:
    def __init__(self) -> None:
        self._jobs: Dict[str, _JobState] = {}
        self._lock = threading.Lock()
        self._queue: "queue.Queue[str]" = queue.Queue()
        self._stop = threading.Event()
        self._delete_timers: dict[str, threading.Timer] = {}

        DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
        self._remove_orphaned_storage()
        self._workers = [
            threading.Thread(target=self._worker_loop, daemon=True)
            for _ in range(MAX_CONCURRENT_DOWNLOADS)
        ]
        for thread in self._workers:
            thread.start()

        threading.Thread(target=self._cleanup_loop, daemon=True).start()

    def submit_job(self, job: DownloadJob) -> None:
        work_dir = DOWNLOAD_DIR / job.id
        work_dir.mkdir(parents=True, exist_ok=True)
        with self._lock:
            self._jobs[job.id] = _JobState(job=job)
        self._queue.put(job.id)

    def get_job(self, job_id: str) -> Optional[DownloadJob]:
        self.cleanup_expired_jobs()
        with self._lock:
            state = self._jobs.get(job_id)
            return state.job if state else None

    def list_jobs(self) -> list[DownloadJob]:
        self.cleanup_expired_jobs()
        with self._lock:
            return [state.job for state in self._jobs.values() if state.job.visible]

    def remove_job(self, job_id: str) -> bool:
        with self._lock:
            state = self._jobs.get(job_id)
            if not state:
                return False

            state.job.visible = False
            state.job.status = JobStatus.cancelled
            state.job.message = "Removed by user"
            state.job.updated_at = datetime.now(timezone.utc)
            if state.process and state.process.poll() is None:
                try:
                    state.process.terminate()
                except Exception:
                    pass
            state.job.error = None
            return True

    def remove_completed_job(self, job_id: str) -> None:
        with self._lock:
            state = self._jobs.get(job_id)
            if state:
                state.job.visible = False
                state.job.downloaded_at = datetime.now(timezone.utc)
                state.job.updated_at = state.job.downloaded_at
                state.job.message = "Downloaded by user"
                self._cancel_delete_timer(job_id)
                self._jobs.pop(job_id, None)
        self._remove_job_storage(job_id)

    def cleanup_expired_jobs(self) -> None:
        now = datetime.now(timezone.utc)
        to_delete = self._expired_job_ids(now)
        for job_id in to_delete:
            self._delete_job(job_id)
        self._remove_orphaned_storage()

    def _worker_loop(self) -> None:
        while not self._stop.is_set():
            job_id = self._queue.get()
            if self._stop.is_set():
                break
            try:
                self._process_job(job_id)
            finally:
                self._queue.task_done()

    def _process_job(self, job_id: str) -> None:
        with self._lock:
            state = self._jobs.get(job_id)
            if not state:
                return
            if not state.job.visible or state.job.status != JobStatus.queued:
                return
            state.job.status = JobStatus.downloading
            state.job.message = "Preparing download"
            state.job.updated_at = datetime.now(timezone.utc)

        sources = [state.job.url]
        if is_spotify_url(state.job.url):
            fallback_query = spotify_oembed_query(state.job.url)
            if fallback_query:
                sources.append(f"ytsearch1:{fallback_query}")

        for source in dict.fromkeys(sources):
            if self._is_cancelled(state):
                return
            if self._run_with_ytdlp(state, source):
                return

        self._set_status(state, JobStatus.error, "All source variants failed")

    def _run_with_ytdlp(self, state: _JobState, source: str) -> bool:
        work_dir = DOWNLOAD_DIR / state.job.id
        output_path = str(work_dir / f"{state.job.id}.%(ext)s")
        cmd = self._build_command(state.job, output_path, source)

        with self._lock:
            state.job.message = f"Using source: {source}"
            state.job.updated_at = datetime.now(timezone.utc)

        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            universal_newlines=True,
            bufsize=1,
        )

        with self._lock:
            state.process = process

        try:
            while True:
                if self._is_cancelled(state):
                    if process.poll() is None:
                        process.terminate()
                    return False
                line = process.stdout.readline() if process.stdout else ""
                if not line:
                    break
                self._handle_progress_line(state, line)

            code = process.wait()
            if code != 0:
                if self._is_cancelled(state):
                    return False
                self._set_status(state, JobStatus.error, "yt-dlp failed")
                return False
            return self._finalize_output(state, work_dir)
        except subprocess.TimeoutExpired:
            process.kill()
            self._set_status(state, JobStatus.error, "yt-dlp timeout")
            return False
        except Exception as exc:
            process.kill()
            self._set_status(state, JobStatus.error, str(exc))
            return False
        finally:
            with self._lock:
                state.process = None

    def _build_command(self, job: DownloadJob, output_path: str, source: str) -> list[str]:
        cmd = [
            YTDLP_BINARY,
            "--newline",
            "--no-playlist",
            "--restrict-filenames",
            "--progress",
            "--no-warnings",
            "-o",
            output_path,
            source,
        ]

        if job.mode == DownloadMode.audio:
            audio_args = [
                "--extract-audio",
                "--audio-format",
                job.format,
            ]
            if job.quality:
                audio_args.extend(["--audio-quality", job.quality])
            cmd = cmd[:5] + audio_args + cmd[5:]
            return cmd

        video_args = [
            "-f",
            "bestvideo*+bestaudio/best",
            "--merge-output-format",
            job.format,
        ]
        if job.quality and job.quality != "best":
            video_args.extend(["-S", f"height:{job.quality}"])
        cmd = cmd[:-1] + video_args + [source]
        return cmd

    def _finalize_output(self, state: _JobState, work_dir: Path) -> bool:
        output = choose_output_file(state.job.id, work_dir, state.job.format, [f"*.{ext}" for ext in KNOWN_EXTENSIONS])
        if not output:
            self._set_status(state, JobStatus.error, "Output file missing")
            return False
        if not output.exists():
            self._set_status(state, JobStatus.error, "Output file removed before completion")
            return False
        output = Path(output)
        state.job.file_name = output.name
        state.job.file_size = output.stat().st_size
        state.job.progress = 100
        self._set_status(state, JobStatus.done, "Done")
        self._schedule_completed_job_cleanup(state.job.id)
        return True

    def _handle_progress_line(self, state: _JobState, line: str) -> None:
        stripped = line.strip()
        if any(marker in stripped for marker in _PROCESSING_MARKERS):
            self._set_status(state, JobStatus.converting, self._friendly_progress_message(stripped))
            return

        progress_match = _PROGRESS_RE.search(line)
        if progress_match:
            percent = int(float(progress_match.group(1)))
            if percent >= 100 and state.job.status != JobStatus.done:
                percent = 99
            self._set_progress(state, max(0, min(99, percent)), self._friendly_progress_message(stripped))

    def _set_progress(self, state: _JobState, percent: int, message: str) -> None:
        with self._lock:
            state.job.progress = percent
            state.job.message = message
            state.job.updated_at = datetime.now(timezone.utc)

    def _friendly_progress_message(self, line: str) -> str:
        if "[Merger]" in line or "Merging formats" in line:
            return "Склеиваю видео и звук"
        if "[ExtractAudio]" in line:
            return "Извлекаю аудио"
        if "[VideoConvertor]" in line:
            return "Конвертирую видео"
        if "[Fixup" in line:
            return "Проверяю контейнер файла"
        if "[MoveFiles]" in line or "Deleting original file" in line:
            return "Финализирую файл"
        if line.startswith("[download]"):
            return "Скачиваю части файла"
        return line

    def _is_cancelled(self, state: _JobState) -> bool:
        return state.job.status == JobStatus.cancelled

    def _set_status(self, state: _JobState, status: JobStatus, message: str) -> None:
        with self._lock:
            now = datetime.now(timezone.utc)
            state.job.status = status
            state.job.message = message
            state.job.updated_at = now
            if status == JobStatus.done and state.job.completed_at is None:
                state.job.completed_at = now

    def _cleanup_loop(self) -> None:
        while not self._stop.is_set():
            self.cleanup_expired_jobs()
            time.sleep(CLEANUP_INTERVAL_SECONDS)

    def _expired_job_ids(self, now: datetime) -> list[str]:
        to_delete = []
        with self._lock:
            for job_id, state in self._jobs.items():
                job = state.job
                if not job.visible and now.timestamp() - job.updated_at.timestamp() >= JOB_TTL_SECONDS:
                    to_delete.append(job_id)
                    continue
                if job.status == JobStatus.done and job.completed_at:
                    if now.timestamp() - job.completed_at.timestamp() >= JOB_TTL_SECONDS:
                        to_delete.append(job_id)
                        continue
                if job.status in {JobStatus.error, JobStatus.cancelled}:
                    if now.timestamp() - job.updated_at.timestamp() >= JOB_TTL_SECONDS:
                        to_delete.append(job_id)
        return to_delete

    def _delete_job(self, job_id: str) -> None:
        with self._lock:
            self._cancel_delete_timer(job_id)
            state = self._jobs.get(job_id)
            if state and state.process and state.process.poll() is None:
                try:
                    state.process.terminate()
                except Exception:
                    pass
            self._jobs.pop(job_id, None)
        self._remove_job_storage(job_id)

    def _schedule_completed_job_cleanup(self, job_id: str) -> None:
        timer = threading.Timer(JOB_TTL_SECONDS, self._delete_job, args=[job_id])
        timer.daemon = True
        with self._lock:
            self._cancel_delete_timer(job_id)
            self._delete_timers[job_id] = timer
        timer.start()

    def _cancel_delete_timer(self, job_id: str) -> None:
        timer = self._delete_timers.pop(job_id, None)
        if timer:
            timer.cancel()

    def _remove_job_storage(self, job_id: str) -> None:
        work_dir = DOWNLOAD_DIR / job_id
        if work_dir.exists():
            shutil.rmtree(work_dir, ignore_errors=True)

    def _remove_orphaned_storage(self) -> None:
        now = time.time()
        with self._lock:
            active_job_ids = set(self._jobs)
        for work_dir in DOWNLOAD_DIR.iterdir():
            if not work_dir.is_dir():
                continue
            if work_dir.name in active_job_ids:
                continue
            try:
                if now - work_dir.stat().st_mtime >= JOB_TTL_SECONDS:
                    shutil.rmtree(work_dir, ignore_errors=True)
            except OSError:
                continue

    def shutdown(self) -> None:
        self._stop.set()
        with self._lock:
            for timer in self._delete_timers.values():
                timer.cancel()
            self._delete_timers.clear()
            for state in self._jobs.values():
                if state.process and state.process.poll() is None:
                    try:
                        state.process.terminate()
                    except Exception:
                        pass
