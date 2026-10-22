import io
import json
import shutil
import subprocess

import pytest

from pages import voice


def install_fake_polly(monkeypatch, marks, seconds):
    class Polly:
        def synthesize_speech(self, **kw):
            assert kw["Engine"] == "neural" and kw["LanguageCode"] == "en-IN"
            if kw["OutputFormat"] == "json":
                body = "\n".join(json.dumps(m) for m in marks).encode()
            else:
                body = b"mp3"
            return {"AudioStream": io.BytesIO(body)}

    monkeypatch.setattr(voice, "_polly", lambda: Polly())
    monkeypatch.setattr(subprocess, "run", lambda cmd, **kw: subprocess.CompletedProcess(cmd, 0, f"{seconds}\n", ""))


def test_speak_keeps_punctuation_and_ends_each_word(monkeypatch, tmp_path):
    text = "Cats sleep 16h."
    marks = [{"time": 0, "type": "word", "start": 0, "end": 4, "value": "Cats"},
             {"time": 400, "type": "word", "start": 5, "end": 10, "value": "sleep"},
             {"time": 900, "type": "word", "start": 11, "end": 14, "value": "16h"}]
    monkeypatch.setenv("PAGES_TTS", "polly")
    install_fake_polly(monkeypatch, marks, seconds=1.6)
    words, seconds = voice.speak(text, "Kajal", tmp_path / "v.mp3")
    assert [w["word"] for w in words] == ["Cats", "sleep", "16h."]
    assert (words[0]["end"], words[-1]["end"], seconds) == (0.4, 1.6, 1.6)
    assert (tmp_path / "v.mp3").read_bytes() == b"mp3"


def test_speak_uses_byte_offsets(monkeypatch, tmp_path):
    text = "Café ok, yes"
    marks = [{"time": 0, "type": "word", "start": 0, "end": 5, "value": "Café"},
             {"time": 300, "type": "word", "start": 6, "end": 8, "value": "ok"},
             {"time": 600, "type": "word", "start": 10, "end": 13, "value": "yes"}]
    monkeypatch.setenv("PAGES_TTS", "polly")
    install_fake_polly(monkeypatch, marks, seconds=1.0)
    words, _ = voice.speak(text, "Kajal", tmp_path / "v.mp3")
    assert [w["word"] for w in words] == ["Café", "ok,", "yes"]


def fake_say(monkeypatch, durations, fail=False):
    calls, n = [], iter(durations)

    def run(cmd, **kw):
        calls.append(cmd)
        if cmd[0] == "say":
            return subprocess.CompletedProcess(cmd, 1 if fail else 0, "", "bad voice")
        if cmd[0] == "ffprobe" and cmd[-1].endswith(".aiff"):
            return subprocess.CompletedProcess(cmd, 0, f"{next(n)}\n", "")
        if cmd[0] == "ffprobe":
            return subprocess.CompletedProcess(cmd, 0, f"{sum(durations)}\n", "")
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setenv("PAGES_TTS", "say")
    monkeypatch.setattr(subprocess, "run", run)
    return calls


def test_say_times_words_per_sentence(monkeypatch, tmp_path):
    calls = fake_say(monkeypatch, [1.0, 2.0])
    words, seconds = voice.speak("Cats blink. It means trust", "Tara", tmp_path / "v.mp3")
    says = [c for c in calls if c[0] == "say"]
    assert [c[:3] + c[6:] for c in says] == [["say", "-v", "Tara", "Cats blink."], ["say", "-v", "Tara", "It means trust"]]
    assert says[0][3] == "-o" and says[0][4].endswith("0.aiff")
    concat = next(c for c in calls if c[0] == "ffmpeg")
    assert "libmp3lame" in concat and concat[-1] == str(tmp_path / "v.mp3")
    assert [w["word"] for w in words] == ["Cats", "blink.", "It", "means", "trust"]
    # sentence 1: weights 6, 8 over 1 s; sentence 2: weights 4, 7, 7 over 2 s from 1.0
    assert (words[0]["end"], words[1]["end"]) == (0.429, 1.0)
    assert (words[2]["start"], words[3]["start"]) == (1.0, 1.444)
    assert words[-1]["end"] == seconds == 3.0


def test_say_unknown_voice_raises(monkeypatch, tmp_path):
    fake_say(monkeypatch, [1.0], fail=True)
    with pytest.raises(RuntimeError, match="Nobody"):
        voice.speak("Hi.", "Nobody", tmp_path / "v.mp3")


def test_say_keeps_tokens_with_inner_dots(monkeypatch, tmp_path):
    calls = fake_say(monkeypatch, [2.0, 1.0])
    text = "Cats sleep 3.5 hours a day. Really!"
    words, _ = voice.speak(text, "Tara", tmp_path / "v.mp3")
    assert [w["word"] for w in words] == text.split()
    assert [c[-1] for c in calls if c[0] == "say"] == ["Cats sleep 3.5 hours a day.", "Really!"]


def test_say_dash_sentence_is_not_an_option(monkeypatch, tmp_path):
    calls = fake_say(monkeypatch, [1.0])
    voice.speak("-5 degrees.", "Tara", tmp_path / "v.mp3")
    say = next(c for c in calls if c[0] == "say")
    assert say[-2:] == ["--", "-5 degrees."]


@pytest.mark.parametrize("text", ["", "  ", "...!"])
def test_say_empty_text_raises(monkeypatch, tmp_path, text):
    calls = fake_say(monkeypatch, [1.0])
    with pytest.raises(ValueError, match="empty text"):
        voice.speak(text, "Tara", tmp_path / "v.mp3")
    assert calls == []


@pytest.mark.slow
@pytest.mark.skipif(shutil.which("say") is None, reason="needs macOS say")
def test_say_really_speaks(monkeypatch, tmp_path):
    monkeypatch.setenv("PAGES_TTS", "say")
    words, seconds = voice.speak("Cats slow blink. It means trust!", "Tara", tmp_path / "v.mp3")
    assert (tmp_path / "v.mp3").stat().st_size > 0 and seconds > 1
    assert words[-1]["word"] == "trust!" and words[-1]["end"] == seconds
