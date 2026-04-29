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

        DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
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
        with self._lock:
            state = self._jobs.get(job_id)
            return state.job if state else None

    def list_jobs(self) -> list[DownloadJob]:
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
        return True

    def _handle_progress_line(self, state: _JobState, line: str) -> None:
        progress_match = _PROGRESS_RE.search(line)
        if progress_match:
            percent = int(float(progress_match.group(1)))
            self._set_progress(state, max(0, min(100, percent)), line.strip())

        if "Destination:" in line and ("ExtractAudio" in line or "ffmpeg" in line):
            self._set_status(state, JobStatus.converting, line.strip())

    def _set_progress(self, state: _JobState, percent: int, message: str) -> None:
        with self._lock:
            state.job.progress = percent
            state.job.message = message
            state.job.updated_at = datetime.now(timezone.utc)

    def _is_cancelled(self, state: _JobState) -> bool:
        return state.job.status == JobStatus.cancelled

    def _set_status(self, state: _JobState, status: JobStatus, message: str) -> None:
        with self._lock:
            state.job.status = status
            state.job.message = message
            state.job.updated_at = datetime.now(timezone.utc)

    def _cleanup_loop(self) -> None:
        while not self._stop.is_set():
            deadline = datetime.now(timezone.utc).timestamp()
            to_delete = []
            with self._lock:
                for job_id, state in self._jobs.items():
                    if not state.job.visible and deadline - state.job.created_at.timestamp() > JOB_TTL_SECONDS:
                        to_delete.append(job_id)
                        continue
                    if state.job.status in {JobStatus.done, JobStatus.error, JobStatus.cancelled}:
                        if deadline - state.job.created_at.timestamp() > JOB_TTL_SECONDS:
                            to_delete.append(job_id)

            for job_id in to_delete:
                self._remove_job_storage(job_id)
                with self._lock:
                    state = self._jobs.get(job_id)
                    if not state:
                        continue
                    if state.process and state.process.poll() is None:
                        try:
                            state.process.terminate()
                        except Exception:
                            pass
                    self._jobs.pop(job_id, None)
            time.sleep(CLEANUP_INTERVAL_SECONDS)

    def _remove_job_storage(self, job_id: str) -> None:
        work_dir = DOWNLOAD_DIR / job_id
        if work_dir.exists():
            shutil.rmtree(work_dir, ignore_errors=True)

    def shutdown(self) -> None:
        self._stop.set()
        with self._lock:
            for state in self._jobs.values():
                if state.process and state.process.poll() is None:
                    try:
                        state.process.terminate()
                    except Exception:
                        pass
