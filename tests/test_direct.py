import json
import subprocess

from app.direct import build_stream_command, inspect_direct_video, safe_download_filename


def test_inspect_direct_video_filters_single_file_formats(monkeypatch):
    payload = {
        "title": "Example video",
        "thumbnail": "https://img.example/thumb.jpg",
        "duration": 120,
        "formats": [
            {
                "format_id": "22",
                "ext": "mp4",
                "url": "https://media.example/720.mp4",
                "protocol": "https",
                "vcodec": "avc1",
                "acodec": "mp4a",
                "height": 720,
                "width": 1280,
                "fps": 30,
                "filesize": 1000,
                "tbr": 1500,
            },
            {
                "format_id": "137",
                "ext": "mp4",
                "url": "https://media.example/video-only.mp4",
                "protocol": "https",
                "vcodec": "avc1",
                "acodec": "none",
                "height": 1080,
            },
            {
                "format_id": "hls",
                "ext": "mp4",
                "url": "https://media.example/playlist.m3u8",
                "protocol": "m3u8_native",
                "vcodec": "avc1",
                "acodec": "mp4a",
                "height": 1080,
            },
        ],
    }

    def fake_run(command, **_kwargs):
        return subprocess.CompletedProcess(command, 0, stdout=json.dumps(payload), stderr="")

    monkeypatch.setattr("app.direct.subprocess.run", fake_run)

    media = inspect_direct_video("https://www.youtube.com/watch?v=dQw4w9WgXcQ")

    assert media.title == "Example video"
    assert len(media.formats) == 1
    assert media.formats[0].format_id == "22"
    assert media.formats[0].resolution == "720p"


def test_build_stream_command_uses_stdout():
    command = build_stream_command("https://www.youtube.com/watch?v=dQw4w9WgXcQ", "22")

    assert "-o" in command
    assert command[command.index("-o") + 1] == "-"
    assert command[command.index("-f") + 1] == "22"


def test_safe_download_filename():
    assert safe_download_filename("Плохое:/ Name?", "mp4") == "Плохое Name.mp4"
