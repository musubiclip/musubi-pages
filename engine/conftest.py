import json
import subprocess

import pytest

from engine.clipper import group_segments


def pytest_configure(config):
    config.addinivalue_line("markers", "slow: renders through ffmpeg and HyperFrames")


def ffmpeg(*args):
    subprocess.run(["ffmpeg", "-v", "error", "-y", *args], check=True)


@pytest.fixture(scope="session")
def fixture_workdir(tmp_path_factory):
    """A 60 s 1920x1080 section with a tone, and a transcript of synthetic words every half second."""
    workdir = tmp_path_factory.mktemp("video")
    (workdir / "sections").mkdir()
    ffmpeg("-f", "lavfi", "-i", "testsrc2=size=1920x1080:rate=30:duration=60", "-f", "lavfi", "-i", "sine=frequency=220:duration=60",
           "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest",
           str(workdir / "sections" / "0.00-60.00.mp4"))
    words = [{"word": f"word{i}." if i % 10 == 9 else f"word{i}", "start": i * 0.5, "end": i * 0.5 + 0.4} for i in range(120)]
    (workdir / "transcript.json").write_text(json.dumps({"language": "en", "source": "youtube", "segments": group_segments(words)}))
    (workdir / "meta.json").write_text(json.dumps({"title": "fixture", "url": "https://youtu.be/x", "language": "en"}))
    return workdir


def tone(path, seconds, frequency):
    ffmpeg("-f", "lavfi", "-i", f"sine=frequency={frequency}:duration={seconds}", "-c:a", "libmp3lame", str(path))
    return path


@pytest.fixture(scope="session")
def vo_4s(tmp_path_factory):
    return tone(tmp_path_factory.mktemp("vo") / "intro.mp3", 4, 660)


@pytest.fixture(scope="session")
def vo_3s(tmp_path_factory):
    return tone(tmp_path_factory.mktemp("vo") / "outro.mp3", 3, 880)
