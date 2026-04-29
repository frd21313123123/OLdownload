# Local Media Downloader

This project is a local web app for downloading media from supported sources.

Supported sources:
- YouTube
- X / Twitter
- YouTube Music (via YouTube extractor in yt-dlp)
- Spotify URLs with best-effort fallback via `open.spotify.com` oEmbed + YouTube search

## Features
- Create audio or video download jobs from a single page
- Select format and quality
- Track per-job status and progress
- Retry or remove jobs from the UI
- Download finished files via API
- Download videos directly in the user's browser without storing them on the server when the source provides a single-file stream
- In-process cleanup of old files and jobs

## Quick start

1. Install dependencies:
   ```bash
   python -m venv .venv
   .venv\Scripts\activate
   pip install -r requirements.txt
   ```
2. Run server:
   ```bash
   python run.py
   ```
3. Open:
   - `http://127.0.0.1:8000/`

## API
- `POST /api/download`
  - body: `{ url, mode: "audio"|"video", format, quality }`
- `POST /api/direct-link`
  - body: `{ url, mode: "video", format, quality }`
  - returns `{ url }` with a temporary direct media URL
- `GET /api/jobs`
- `GET /api/jobs/{id}`
- `DELETE /api/jobs/{id}`
- `GET /api/download/{id}`
- `GET /health`

## Notes
- This app is built for local/private use.
- Ensure `yt-dlp` and `ffmpeg` are installed in your system PATH.
- Output files are stored under `downloads/<job_id>/`.
- Direct video links are temporary and depend on whether the source exposes a single downloadable video stream for the selected format/quality.
- Use legally compliant sources and content only.
