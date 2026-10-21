"""Polly voice with word timings."""
import json
import os
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
        _, seconds = speak("Testing one two", os.environ.get("PAGES_VOICE", "Kajal"), Path(d) / "t.mp3")
        print(f"spoke {seconds} s")
    if os.environ.get("PAGES_LLM") == "bedrock":
        print(llm.ask("Reply with ok true.", Ok))
