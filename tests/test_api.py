from fastapi.testclient import TestClient

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
