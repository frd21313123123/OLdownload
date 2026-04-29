from fastapi.testclient import TestClient

import app.main as main
from app.direct import DirectMediaLink
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
    def fake_resolve(url: str, fmt: str, quality: str):
        assert url == "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
        assert fmt == "mp4"
        assert quality == "720"
        return DirectMediaLink(url="https://media.example/video.mp4")

    monkeypatch.setattr(main, "resolve_direct_video_link", fake_resolve)

    response = client.post(
        "/api/direct-link",
        json={"url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ", "mode": "video", "format": "mp4", "quality": "720"},
    )

    assert response.status_code == 200
    assert response.json() == {"url": "https://media.example/video.mp4"}


def test_reject_direct_audio_link():
    response = client.post(
        "/api/direct-link",
        json={"url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ", "mode": "audio", "format": "mp3", "quality": "192"},
    )
    assert response.status_code == 400
