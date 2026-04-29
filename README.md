# Local Media Downloader

This project is a local web app for downloading media from supported sources.

Supported sources:
- YouTube
- X / Twitter
- YouTube Music (via YouTube extractor in yt-dlp)
- Spotify URLs with best-effort fallback via `open.spotify.com` oEmbed + YouTube search

## Features
- Paste a media URL and fetch available direct video formats
- Show video title, thumbnail, duration, format, quality, and approximate size
- Stream the selected ready-made video file to the browser without writing it to server storage
- Keep the older job API available for fallback/internal use

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
- `POST /api/formats`
  - body: `{ url }`
  - returns title, thumbnail, duration, and direct single-file video formats
- `GET /api/stream?url=...&format_id=...`
  - streams the selected format to the browser as an attachment without saving the media file on disk
- `POST /api/direct-link`
  - body: `{ url, format_id }`
  - returns `{ url }` with the current temporary source media URL
- `POST /api/download`
  - body: `{ url, mode: "audio"|"video", format, quality }`
- `GET /api/jobs`
- `GET /api/jobs/{id}`
- `DELETE /api/jobs/{id}`
- `GET /api/download/{id}`
- `GET /health`

## Notes
- This app is built for local/private use.
- Ensure `yt-dlp` and `ffmpeg` are installed in your system PATH.
- The main browser flow only exposes single-file formats that already contain both video and audio.
- If a source only provides separate video/audio streams, a single direct browser download is not possible without server-side or client-side merging.
- The legacy job API stores output files under `downloads/<job_id>/`; the main UI does not use it.
- Use legally compliant sources and content only.
