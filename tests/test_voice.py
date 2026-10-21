import io
import json
import subprocess

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
    install_fake_polly(monkeypatch, marks, seconds=1.0)
    words, _ = voice.speak(text, "Kajal", tmp_path / "v.mp3")
    assert [w["word"] for w in words] == ["Café", "ok,", "yes"]
