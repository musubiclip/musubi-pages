"""Voice with word timings: macOS `say` locally (default), Polly when PAGES_TTS=polly."""
import json
import os
import re
import subprocess
import tempfile
from pathlib import Path

from pydantic import BaseModel

from pages import llm


def _polly():
    import boto3

    return boto3.client("polly", region_name=os.environ.get("AWS_REGION", "ap-south-1"))


def _seconds(path: Path) -> float:
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
                         capture_output=True, text=True, check=True).stdout
    return float(out.strip())


def speak(text: str, voice: str, out: Path) -> tuple[list[dict], float]:
    if os.environ.get("PAGES_TTS", "say") == "polly":
        return _speak_polly(text, voice, out)
    return _speak_say(text, voice, out)


def _speak_say(text: str, voice: str, out: Path) -> tuple[list[dict], float]:
    if not re.search(r"\w", text):
        raise ValueError("empty text")
    sentences = [s for s in re.split(r"(?<=[.?!])\s+", text.strip()) if s]
    words, offset = [], 0.0
    with tempfile.TemporaryDirectory() as d:
        parts = []
        for i, sentence in enumerate(sentences):
            part = Path(d) / f"{i}.aiff"
            if subprocess.run(["say", "-v", voice, "-o", str(part), "--", sentence], capture_output=True).returncode:
                raise RuntimeError(f"say failed for voice {voice!r}")
            length = _seconds(part)
            # same weighting the engine uses for english.json
            tokens = sentence.split()
            total, done = sum(len(t) + 2 for t in tokens), 0
            for t in tokens:
                start = offset + length * done / total
                done += len(t) + 2
                words.append({"word": t, "start": round(start, 3), "end": round(offset + length * done / total, 3)})
            offset += length
            parts.append(part)
        inputs = [a for p in parts for a in ("-i", str(p))]
        out.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(["ffmpeg", "-y", "-v", "error", *inputs, "-filter_complex",
                        "".join(f"[{i}:a]" for i in range(len(parts))) + f"concat=n={len(parts)}:v=0:a=1",
                        "-ar", "44100", "-ac", "1", "-c:a", "libmp3lame", str(out)], capture_output=True, check=True)
    seconds = round(_seconds(out), 3)
    if words:
        words[-1]["end"] = seconds
    return words, seconds


def _speak_polly(text: str, voice: str, out: Path) -> tuple[list[dict], float]:
    polly = _polly()
    args = dict(Text=text, VoiceId=voice, Engine="neural", LanguageCode="en-IN")
    out.write_bytes(polly.synthesize_speech(OutputFormat="mp3", **args)["AudioStream"].read())
    raw = polly.synthesize_speech(OutputFormat="json", SpeechMarkTypes=["word"], **args)["AudioStream"].read()
    marks = [json.loads(line) for line in raw.decode().splitlines() if line.strip()]
    seconds = round(_seconds(out), 3)

    data = text.encode("utf-8")
    words = []
    for i, m in enumerate(marks):
        end = m["end"]
        # carry trailing punctuation ("16h" -> "16h.") up to the next space or word
        limit = marks[i + 1]["start"] if i + 1 < len(marks) else len(data)
        while end < limit and not data[end:end + 1].isspace():
            end += 1
        stop = marks[i + 1]["time"] / 1000 if i + 1 < len(marks) else seconds
        words.append({"word": data[m["start"]:end].decode("utf-8"), "start": round(m["time"] / 1000, 3),
                      "end": round(stop, 3)})
    return words, seconds


class Ok(BaseModel):
    ok: bool


def check_aws() -> None:
    """Backs `pages check-aws`."""
    for v in _polly().describe_voices(LanguageCode="en-IN")["Voices"]:
        print(v["Id"], v.get("SupportedEngines"))
    with tempfile.TemporaryDirectory() as d:
        _, seconds = _speak_polly("Testing one two", os.environ.get("PAGES_VOICE", "Kajal"), Path(d) / "t.mp3")
        print(f"spoke {seconds} s")
    if os.environ.get("PAGES_LLM") == "bedrock":
        print(llm.ask("Reply with ok true.", Ok))
