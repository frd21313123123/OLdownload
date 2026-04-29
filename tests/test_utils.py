from app.utils import validate_mode_and_format, normalize_url


def test_audio_formats():
    assert validate_mode_and_format("audio", "mp3", "192") == ("mp3", "192")
    assert validate_mode_and_format("audio", "flac", None) == ("flac", None)


def test_invalid_audio_quality():
    try:
        validate_mode_and_format("audio", "mp3", "1")
    except ValueError as exc:
        assert "quality" in str(exc).lower()
    else:
        raise AssertionError("Expected validation error")


def test_video_formats():
    assert validate_mode_and_format("video", "mp4", "best") == ("mp4", "best")
    assert validate_mode_and_format("video", "webm", "720") == ("webm", "720")


def test_invalid_source_host():
    try:
        normalize_url("https://example.com/video")
    except ValueError:
        return
    raise AssertionError("Expected validation error")
