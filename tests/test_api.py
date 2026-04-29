from fastapi.testclient import TestClient

import app.main as main
from app.direct import DirectMediaFormat, DirectMediaInfo, DirectMediaLink
from app.main import app


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
