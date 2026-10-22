import json
import subprocess

import numpy as np
import pytest

from engine import montage
from engine.montage import SR


def click_track(bpm, seconds=40, start=0.3, drop_at=None):
    """Hi-hat clicks on every beat, a kick on every 4th from beat 1 (the downbeats); the kick gets heavy at drop_at."""
    x = np.zeros(int(seconds * SR), dtype=np.float32)
    period = 60 / bpm
    t = np.arange(int(0.08 * SR)) / SR
    hat = (np.random.default_rng(1).standard_normal(len(t)) * np.exp(-t * 80)).astype(np.float32) * 0.3
    kick = (np.sin(2 * np.pi * 55 * t) * np.exp(-t * 25)).astype(np.float32)
    for k, at in enumerate(np.arange(start, seconds - 0.2, period)):
        i = int(at * SR)
        x[i:i + len(t)] += hat
        if k % 4 == 1:
            x[i:i + len(t)] += kick * (1.0 if drop_at is not None and at >= drop_at else 0.25)
    return x, period


@pytest.mark.parametrize("bpm", [96, 120, 140, 152])
def test_beat_grid_finds_the_tempo_and_beats_of_a_click_track(bpm):
    x, period = click_track(bpm)
    grid = montage.beat_grid(samples=x)
    assert abs(grid["bpm"] - bpm) < 0.5
    truth = np.arange(0.3, 39.8, period)
    for t in grid["beats"][1:-1]:
        assert np.min(np.abs(truth - t)) < 0.02  # every beat within 20 ms, all the way through
    downs = np.arange(0.3 + period, 39.8, 4 * period)
    assert all(np.min(np.abs(downs - t)) < 0.02 for t in grid["downbeats"])


def test_the_drop_is_the_first_strong_downbeat():
    x, period = click_track(120, drop_at=8.0)
    grid = montage.beat_grid(samples=x)
    drop = montage.find_drop(grid, 1.5)
    assert 8.0 - 0.02 <= drop < 8.0 + 4 * period


def grid_for(bpm, seconds=60):
    x, _ = click_track(bpm, seconds=seconds, drop_at=6.0)
    return montage.beat_grid(samples=x)


def test_visual_plan_cuts_on_beats_with_2_to_8_beat_shots():
    grid = grid_for(128)
    lengths = [1.2, 2.5, 1.0, 3.0, 1.8, 2.2, 1.5, 2.9, 1.1, 2.0]
    p = montage.plan(lengths, grid, "visual")
    beat = p["period"]
    assert all(2 <= c <= 8 for c in p["counts"])
    assert p["counts"][0] * beat >= montage.HOOK_MIN
    assert 15 <= p["cuts"][-1] <= 30
    for t in p["cuts"]:  # every cut is on a beat (to a frame)
        k = t / beat
        assert abs(k - round(k)) * beat <= 1 / 60 + 1e-6
    # the drop: the music starts so a strong downbeat of the bed lands on the first cut
    file_time = p["offset"] + p["drop"]
    assert min(abs(file_time - d) for d in grid["downbeats"]) < 0.03 and file_time >= 6.0 - 0.02
    assert any(abs(p["cuts"][-1] - d) < 0.02 for d in p["downbeats"])  # it ends on a bar line


def test_visual_plan_stretches_a_short_reel_and_trims_a_long_one():
    grid = grid_for(140)
    short = montage.plan([1.0] * 8, grid, "visual")
    assert short["cuts"][-1] >= 15 and all(c <= 8 for c in short["counts"])
    long = montage.plan([3.0] * 15, grid, "visual")
    assert long["cuts"][-1] <= 30 and len(long["counts"]) < 15


def test_speech_plan_lets_every_line_finish():
    grid = grid_for(120)
    lines = [3.2, 4.1, 2.4, 4.9, 3.6]
    p = montage.plan(lines, grid, "speech")
    for n, (a, b) in zip(lines, zip(p["cuts"], p["cuts"][1:])):
        assert b - a >= n + montage.LEAD + montage.TAIL - 1 / 30
    assert 15 <= p["cuts"][-1] <= 30


def test_transitions_vary_and_never_repeat_back_to_back():
    counts = [4, 2, 3, 4, 2, 6, 2, 4, 3, 5, 2, 4]
    for seed in range(20):
        kinds = montage.pick_transitions(len(counts), "visual", counts, seed)
        assert kinds[0] == "drop" and len(kinds) == len(counts) - 1
        assert all(a != b for a, b in zip(kinds, kinds[1:]))
        assert len(set(kinds)) >= 4
        assert all(counts[i] >= 3 for i, k in enumerate(kinds) if k == "ramp")
    assert "ramp" not in montage.pick_transitions(12, "speech", counts, 3)


def test_sfx_only_on_major_transitions_and_spaced():
    cuts = [2.0, 2.9, 3.8, 4.7, 6.0, 9.0]
    kinds = ["drop", "whip", "zoom", "whip", "flash", "whip"]
    cues = montage.sfx_cues(cuts, kinds)
    assert cues[0] == ("impact", 2.0)
    assert [c[0] for c in cues] == ["impact", "whoosh", "whoosh"]  # the 2.9 whip is too close to the drop
    assert all(b[1] - a[1] >= montage.SFX_GAP - 0.2 for a, b in zip(cues, cues[1:]))


def test_text_beats_pop_on_downbeats_after_the_headline():
    downbeats = [round(0.5 + 1.875 * k, 3) for k in range(12)]
    beats = montage.text_beat_times(["10X FASTER", "NO HUMANS NEEDED", "ZERO ERRORS"], downbeats, 2.0, 20.0)
    assert [b["text"] for b in beats] == ["10X FASTER", "NO HUMANS NEEDED", "ZERO ERRORS"]
    for i, b in enumerate(beats):
        assert b["t"] in downbeats and b["t"] >= 2.3 and b["out"] > b["t"]
        if i + 1 < len(beats):
            assert b["out"] < beats[i + 1]["t"]
    assert beats[-1]["out"] <= 19.6


def ffmpeg(*args):
    subprocess.run(["ffmpeg", "-v", "error", "-y", *args], check=True)


@pytest.mark.slow
def test_render_montage_makes_a_beat_cut_reel(fixture_workdir, tmp_path, monkeypatch):
    monkeypatch.setenv("MUSUBI_CLIPS_DIR", str(tmp_path / "work"))
    x, _ = click_track(128, seconds=45, drop_at=4.0)
    (tmp_path / "bed.raw").write_bytes(x.tobytes())
    ffmpeg("-f", "f32le", "-ar", str(SR), "-ac", "1", "-i", str(tmp_path / "bed.raw"), str(tmp_path / "bed.mp3"))
    video = fixture_workdir / "sections" / "0.00-60.00.mp4"
    segments = [{"video": video, "start": 3 * i + 0.5, "end": 3 * i + 2.0} for i in range(10)]
    out = montage.render_montage(segments, tmp_path / "m.mp4", music=tmp_path / "bed.mp3", brand_tag="TECH BAWAAL",
                                 headline="This robot arm carves a statue in three hours flat", accent=["three", "hours"],
                                 text_beats=["10X FASTER", "NO HUMANS"], theme={"hot": "#256dfd", "sun": "#5cff3a", "font": "Poppins"})
    info = json.loads(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=width,height,codec_type:format=duration",
                                      "-of", "json", str(out)], capture_output=True, text=True).stdout)
    video_stream = next(s for s in info["streams"] if s["codec_type"] == "video")
    assert (video_stream["width"], video_stream["height"]) == (1080, 1920)
    assert 15 <= float(info["format"]["duration"]) <= 30.5
    assert out.with_suffix(".jpg").exists()
    html = (tmp_path / "work" / "montage" / "m" / "index.html").read_text()
    assert "TECH BAWAAL" in html and "#256dfd" in html and 'data-media-start=' in html


def test_a_wide_shot_crops_closer_around_the_speaker():
    assert montage.fill_frame(1920, 1080, (1400, 500, 300)).startswith("crop=608:1080:1096:0,")  # a close-up: full height
    wide = montage.fill_frame(1920, 1080, (1400, 500, 60))  # a stage shot: 55% of the height, around the face
    assert wide.startswith("crop=334:594:1233:") and "scale=1080:1920" in wide
    assert montage.fill_frame(1920, 1080).startswith("crop=608:1080:656:0,")  # no face: the centre
