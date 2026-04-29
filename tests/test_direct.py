import subprocess

from app.direct import _single_file_format_selectors, resolve_direct_video_link


def test_direct_selector_fallbacks():
    assert _single_file_format_selectors("mp4", "720") == [
        "best[ext=mp4][vcodec!=none][acodec!=none][height<=720]",
        "best[ext=mp4][vcodec!=none][acodec!=none]",
        "best[vcodec!=none][acodec!=none][height<=720]",
        "best[vcodec!=none][acodec!=none]",
    ]


def test_resolve_direct_link_tries_next_selector(monkeypatch):
    calls = []

    def fake_run(command, **_kwargs):
        calls.append(command)
        if len(calls) == 1:
            return subprocess.CompletedProcess(command, 1, stdout="", stderr="missing format")
        return subprocess.CompletedProcess(command, 0, stdout="https://media.example/video.mp4\n", stderr="")

    monkeypatch.setattr("app.direct.subprocess.run", fake_run)

    media = resolve_direct_video_link("https://www.youtube.com/watch?v=dQw4w9WgXcQ", "mp4", "720")

    assert media.url == "https://media.example/video.mp4"
    assert calls[0][calls[0].index("-f") + 1] == "best[ext=mp4][vcodec!=none][acodec!=none][height<=720]"
    assert calls[1][calls[1].index("-f") + 1] == "best[ext=mp4][vcodec!=none][acodec!=none]"
