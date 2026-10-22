# /// script
# requires-python = ">=3.12,<3.13"
# dependencies = ["opencv-python-headless"]
# ///
import argparse
import contextlib
import functools
import html
import json
import os
import re
import shutil
import statistics
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent
FONTS = SKILL_DIR / "assets" / "fonts"
REEL_TEMPLATES = {"v1": SKILL_DIR / "assets" / "reel" / "v1.html", "v2": SKILL_DIR / "assets" / "reel" / "v2.html"}
STYLE = {"design": "v2", "keep_height": 1.0, "watermark": False}
WATERMARK = SKILL_DIR / "assets" / "brand" / "watermark.png"
HYPERFRAMES = "hyperframes@0.8.96"
JOBS = int(os.environ.get("MUSUBI_CLIPS_JOBS", 3))
MUSIC = {"file": None, "volume": 0.10}
DUCK = 0.6  # music level under speech, as a share of its base volume
SFX = SKILL_DIR / "assets" / "sfx"
SFX_VOLUME = {"whoosh": 0.5, "impact": 0.6, "pop": 0.4, "swoosh": 0.35}
MIN_SPEAKER = 0.6  # share of sampled frames that must show a face
VIRAL = {"controversy": 0.30, "insight": 0.35, "engagement": 0.20, "topic_match": 0.15}  # get-y2b-clips (MIT)
END = {"choice": None, "name": "", "line": "", "screen": None}
END_SECONDS = 2.6
IMAGE_TYPES = {"image/svg+xml": ".svg", "image/png": ".png", "image/jpeg": ".jpg", "image/webp": ".webp", "image/gif": ".gif"}
FACE_MODEL = Path.home() / ".cache" / "musubi-clips" / "face_detection_yunet_2023mar.onnx"
FACE_MODEL_URL = "https://github.com/opencv/opencv_zoo/raw/main/models/face_detection_yunet/face_detection_yunet_2023mar.onnx"
YTDLP = ["yt-dlp"] + (["--cookies-from-browser", os.environ["MUSUBI_CLIPS_COOKIES"]] if os.environ.get("MUSUBI_CLIPS_COOKIES") else [])
OUT_W, OUT_H = 1080, 1920
HOOK_SECONDS = 3.0
MIN_CLIP, MAX_CLIP = 12.0, 90.0
MIN_FACE = 0.05
LEAD, TAIL = 0.25, 0.7
SENTENCE_REACH = 1.2
FADE_IN, FADE_OUT, JOIN_FADE = 0.15, 0.5, 0.08
SECTION_PAD = 8.0


def work_root():
    return Path(os.environ.get("MUSUBI_CLIPS_DIR", Path.home() / "MusubiClips"))


def offline():
    """Server mode: never call YouTube, use only the sections already fetched."""
    return os.environ.get("MUSUBI_CLIPS_OFFLINE") == "1"


def run(cmd, cwd=None):
    try:
        return subprocess.run(cmd, check=True, capture_output=True, text=True, encoding="utf-8", errors="replace", cwd=cwd)
    except subprocess.CalledProcessError as error:
        print(f"{cmd[0]} failed: {(error.stderr or '')[-800:]}", file=sys.stderr)
        raise


def log(msg):
    print(msg, file=sys.stderr, flush=True)


VIDEO_FORMAT = "bv*[height<=1080][vcodec^=avc1]/bv*[height<=1080][ext=mp4]/bv*[height<=1080]"


def fetch(source):
    if Path(source).is_file():
        path = Path(source).resolve()
        workdir = work_root() / re.sub(r"[^A-Za-z0-9_-]", "_", path.stem)
        workdir.mkdir(parents=True, exist_ok=True)
        return workdir, path, {"title": path.stem, "url": "", "path": str(path)}
    video_id = run([*YTDLP, "--print", "id", "--skip-download", source]).stdout.strip().splitlines()[-1]
    workdir = work_root() / video_id
    workdir.mkdir(parents=True, exist_ok=True)
    if not source_audio(workdir):
        log(f"downloading the audio of {source}")
        run([*YTDLP, "-f", "ba[ext=m4a]/ba", "--write-info-json", "--no-playlist",
             "-o", str(workdir / "source-audio.%(ext)s"), source])
    info = json.loads((workdir / "source-audio.info.json").read_text(encoding="utf-8"))
    return workdir, source_audio(workdir), {"title": info.get("title", video_id), "url": info.get("webpage_url", source)}


def source_audio(workdir):
    full = workdir / "source.mp4"
    if full.exists():
        return full
    found = [f for f in workdir.glob("source-audio.*") if not f.name.endswith(".json")]
    return found[0] if found else None



def stream_url(url):
    for command in (["yt-dlp"], YTDLP):
        try:
            return run([*command, "-g", "-f", VIDEO_FORMAT, "--no-playlist", url]).stdout.strip().splitlines()[0]
        except (subprocess.CalledProcessError, IndexError):
            pass
    return "unavailable:"


def cached_stream(workdir, url):
    path = workdir / "stream.json"
    if path.exists():
        saved = json.loads(path.read_text(encoding="utf-8"))
        if saved["expires"] > time.time() + 1800:
            return saved["url"]
    stream = stream_url(url)
    expires = re.search(r"[?&/]expire[=/](\d+)", stream)
    if expires:
        path.write_text(encoding="utf-8", data=json.dumps({"url": stream, "expires": int(expires[1])}))
    return stream


def find_stream(workdir, meta):
    if (workdir / "source.mp4").exists() or not meta.get("url") or offline():
        return None
    log("finding the video stream")
    for attempt in range(3):
        try:
            return cached_stream(workdir, meta["url"])
        except subprocess.CalledProcessError:
            if attempt == 2:
                raise
            time.sleep(30)


def covering_section(folder, start, end):
    """A finished section that holds start to end; waits while another process is still writing one."""
    while True:
        done, writing = None, False
        for f in folder.glob("*.mp4"):
            span = re.fullmatch(r"(\d+\.\d+)-(\d+\.\d+)(\.part)?", f.stem)
            if not span or float(span[1]) > start or float(span[2]) < end:
                continue
            if not span[3]:
                done = f
            elif time.time() - f.stat().st_mtime < 60:
                writing = True
        if done or not writing:
            return done
        time.sleep(2)


@functools.cache
def fast_encoder():
    """Hardware H.264 for the in between files, which are encoded again later; x264 where there is none."""
    encoders = run(["ffmpeg", "-hide_banner", "-encoders"]).stdout
    if "h264_videotoolbox" in encoders:
        return ["-c:v", "h264_videotoolbox", "-b:v", "24M"]
    return ["-c:v", "libx264", "-preset", "veryfast", "-crf", "16"]


def video_section(workdir, meta, clip, stream):
    full = workdir / "source.mp4"
    if full.exists():
        return full, 0.0
    if meta.get("path"):
        return Path(meta["path"]), 0.0
    pieces = pieces_for(clip)
    folder = workdir / "sections"
    folder.mkdir(exist_ok=True)
    found = covering_section(folder, min(a for a, _ in pieces) - 0.5, max(b for _, b in pieces) + 0.5)
    if found:
        return found, float(found.stem.split("-")[0])
    if offline():
        raise RuntimeError(f"no section covers {min(a for a, _ in pieces):.2f}-{max(b for _, b in pieces):.2f}")
    start =max(0.0, min(a for a, _ in pieces) - SECTION_PAD)
    end = max(b for _, b in pieces) + SECTION_PAD
    final = folder / f"{start:.2f}-{end:.2f}.mp4"
    out = final.with_suffix(".part.mp4")
    audio = ["-ss", f"{start}", "-t", f"{end - start}", "-i", str(source_audio(workdir)),
             "-map", "0:v:0", "-map", "1:a:0", *fast_encoder(),
             "-c:a", "aac", "-b:a", "192k", str(out)]
    try:
        run(["ffmpeg", "-y", "-ss", f"{start}", "-t", f"{end - start}", "-i", stream, *audio])
    except subprocess.CalledProcessError:
        out.unlink(missing_ok=True)
        (workdir / "stream.json").unlink(missing_ok=True)
        if not meta.get("url"):
            raise
        piece = final.with_suffix(".video.mp4")
        for attempt in range(3):
            try:
                piece.unlink(missing_ok=True)
                run([*YTDLP, "-f", VIDEO_FORMAT, "--no-playlist", "--download-sections", f"*{start}-{end}",
                     "--force-keyframes-at-cuts", "-o", str(piece), meta["url"]])
                run(["ffmpeg", "-y", "-t", f"{end - start}", "-i", str(piece), *audio])
                break
            except subprocess.CalledProcessError:
                out.unlink(missing_ok=True)
                if attempt == 2:
                    raise
                time.sleep(20)
        piece.unlink(missing_ok=True)
    out.replace(final)
    return final, start


def shifted(clip, words, offset):
    if not offset:
        return clip, words
    moved = {**clip, "start": clip["start"] - offset, "end": clip["end"] - offset,
             "cold_open": [t - offset for t in clip["cold_open"]] if clip["cold_open"] else None,
             "skip": [[a - offset, b - offset] for a, b in clip.get("skip") or []]}
    for key in ("stat", "deal"):
        if isinstance(clip.get(key), dict):
            moved[key] = {**clip[key], **{k: clip[key][k] - offset for k in ("at", "sub_at") if isinstance(clip[key].get(k), (int, float))}}
    if clip.get("cards"):
        moved["cards"] = [{**c, "at": c["at"] - offset} for c in clip["cards"]]
    return moved, [{**w, "start": w["start"] - offset, "end": w["end"] - offset} for w in words]


def youtube_words(caption_file):
    events = json.loads(caption_file.read_text(encoding="utf-8"))["events"]
    tokens = sorted(((e["tStartMs"] + seg.get("tOffsetMs", 0)) / 1000, re.sub(r">>|\[[^\]]*\]", "", seg.get("utf8", "")).strip())
                    for e in events for seg in e.get("segs", []))
    starts, tagged = [], False
    for start, text in tokens:
        tagged = tagged or text.startswith("[")
        if tagged or not text:
            tagged = tagged and "]" not in text
        elif starts and not re.search(r"\w", text):
            starts[-1] = (starts[-1][0], starts[-1][1] + text)
        else:
            starts.append((start, text))
    return [{"word": text, "start": start, "end": min(start + 0.8, following[0] if following else start + 0.5)}
            for (start, text), following in zip(starts, starts[1:] + [None])]


def group_segments(words, gap=0.8, size=14):
    segments, current = [], []
    for word in words:
        if current and (len(current) == size or word["start"] - current[-1]["end"] > gap):
            segments.append(current)
            current = []
        current.append(word)
    if current:
        segments.append(current)
    return [{"start": g[0]["start"], "end": g[-1]["end"], "text": " ".join(w["word"] for w in g), "words": g} for g in segments]


def caption_file(workdir):
    found = (sorted(workdir.glob("captions.en*-orig.json3")) or sorted(workdir.glob("captions.*-orig.json3"))
             or sorted(workdir.glob("captions.en.json3")))
    return found[0] if found else None


def fetch_translated(workdir):
    info = json.loads((workdir / "source-audio.info.json").read_text(encoding="utf-8"))
    for track in info.get("automatic_captions", {}).get("en", []):
        if track.get("ext") == "json3":
            try:
                request = urllib.request.Request(track["url"], headers={"User-Agent": "Mozilla/5.0"})
                (workdir / "captions.en.json3").write_bytes(urllib.request.urlopen(request, timeout=30).read())
            except OSError as error:
                log(f"youtube refused the translated captions: {error}")
            return


def youtube_transcript(workdir, url):
    if not caption_file(workdir):
        subprocess.run([*YTDLP, "--skip-download", "--write-auto-subs", "--sub-langs", ".*-orig", "--sub-format", "json3",
                        "-o", str(workdir / "captions.%(ext)s"), url], capture_output=True)
    if not caption_file(workdir):
        fetch_translated(workdir)
    found = caption_file(workdir)
    words = youtube_words(found) if found else []
    language = found.name.split(".")[1].split("-")[0] if found else "en"
    return {"language": language, "source": "youtube", "segments": group_segments(words)} if words else None


def transcribe(workdir, video, meta):
    cached = workdir / "transcript.json"
    if cached.exists():
        return json.loads(cached.read_text(encoding="utf-8"))
    transcript = youtube_transcript(workdir, meta["url"]) if meta["url"] else None
    if not transcript:
        sys.exit("YouTube has no auto captions for this video, so it cannot be clipped.")
    cached.write_text(encoding="utf-8", data=json.dumps(transcript, ensure_ascii=False))
    return transcript


def all_words(transcript):
    return [w for s in transcript["segments"] for w in s["words"] if w["word"]]


def english_words(workdir, language):
    path = workdir / "english.json"
    if language == "en" and not path.exists():
        return None
    if not path.exists():
        sys.exit("english.json is missing: run `english` and write an English line for every line it lists.")
    words = []
    for line in json.loads(path.read_text(encoding="utf-8")):
        tokens = line["text"].split()
        weights = [len(t) + 2 for t in tokens]
        t, step = line["start"], (line["end"] - line["start"]) / max(sum(weights), 1)
        for token, weight in zip(tokens, weights):
            words.append({"word": token, "start": round(t, 3), "end": round(t + weight * step, 3)})
            t += weight * step
    return sorted(words, key=lambda w: w["start"])


def untranslated(workdir):
    transcript = json.loads((workdir / "transcript.json").read_text(encoding="utf-8"))
    path = workdir / "english.json"
    done = [(l["start"], l["end"]) for l in json.loads(path.read_text(encoding="utf-8"))] if path.exists() else []
    spans = [(m["start"] - 1.5, m["end"] + 1.5) for m in load_moments(workdir)]
    return [f"[{s['start']:.2f}-{s['end']:.2f}] {s['text']}" for s in spoken_sentences(all_words(transcript))
            if any(a < s["end"] and s["start"] < b for a, b in spans)
            and not any(a < s["end"] - 0.3 and s["start"] + 0.3 < b for a, b in done)]


def spoken_sentences(words):
    sentences, current = [], []
    for i, w in enumerate(words):
        current.append(w)
        pause = i + 1 < len(words) and words[i + 1]["start"] - w["end"] > 1.0
        if w["word"][-1:] in ".?!।" or pause or i + 1 == len(words):
            sentences.append({"start": current[0]["start"], "end": current[-1]["end"],
                              "text": " ".join(x["word"] for x in current)})
            current = []
    return sentences


def clip_time(clip, t):
    offset = 0.0
    for a, b in pieces_for(clip):
        if a - 0.05 <= t <= b + 0.05:
            return round(offset + t - a, 3)
        offset += b - a
    return None


def card(clip, key):
    value = clip.get(key)
    if not isinstance(value, dict) or "at" not in value:
        return None
    at = clip_time(clip, value["at"])
    return {**value, "at": at} if at is not None else None


def snap(t, words, edge):
    if not words:  # no speech (animal clips): keep the time as picked
        return t
    if edge == "end":
        whole = [w for w in words if w["word"][-1:] in ".?!\u0964"]
    else:
        whole = [w for i, w in enumerate(words) if i == 0 or words[i - 1]["word"][-1:] in ".?!\u0964"]
    near = [w for w in whole if abs(w[edge] - t) <= SENTENCE_REACH]
    return min(near or words, key=lambda w: abs(w[edge] - t))[edge]


def breathe(start, end, words, lead, tail):
    """Pad a cut so it never clips a syllable, stopping short of the neighbouring words."""
    if not words:
        return start, end
    before = [w for w in words if w["start"] < start - 0.01]
    after = [w for w in words if w["start"] > end - 0.01]
    floor = before[-1]["start"] + 0.4 if before else 0.0
    ceiling = after[0]["start"] - 0.06 if after else end + tail
    return round(min(start, max(start - lead, floor)), 3), round(max(end, min(end + tail, ceiling)), 3)


def rank_score(clip):
    if all(isinstance(clip.get(k), int) for k in VIRAL):
        # pages: the hook weighs most (4 a point), then the virality mix scaled to 5 to 25
        return clip["hook"] * 4 + clip["standalone"] + clip["payoff"] + clip["emotion"] + round(
            5 * sum(clip[k] * w for k, w in VIRAL.items()), 2)
    return clip["hook"] * 2 + clip["standalone"] + clip["payoff"] + clip["emotion"]


def fit_end(start, end, skip, cold, words, cap):
    """An end that keeps the played clip (cold open plus the moment less its skips) within cap seconds,
    on a sentence end when one lands in the second half, else on a word end."""
    def played(e):
        return e - start - sum(min(b, e) - a for a, b in skip if a < e) + (cold[1] - cold[0] if cold else 0)
    if played(end) <= cap:
        return end
    fits = [w for w in words if start < w["end"] < end and played(w["end"] + 0.05) <= cap]
    whole = [w for w in fits if w["word"][-1:] in ".?!\u0964" and w["end"] - start >= cap / 2]
    if whole or fits:
        last = (whole or fits)[-1]["end"]  # a skip never starts within 0.15 s of a word, so the tail is plain time
        return round(min(breathe(start, last, words, 0, 0.3)[1], last + cap - played(last)), 3)
    return round(start + cap - (cold[1] - cold[0] if cold else 0), 3)  # no words: skips only shorten it


def played_seconds(clip):
    return round(sum(b - a for a, b in pieces_for(clip)), 3)


def silence_skips(words, start, end, gap=0.6, air=0.15):
    """Skip spans for pauses longer than gap between words inside start to end, leaving air each side."""
    inside = [w for w in words if start <= w["start"] and w["end"] <= end]
    return [[round(a["end"] + air, 3), round(b["start"] - air, 3)] for a, b in zip(inside, inside[1:])
            if b["start"] - a["end"] > gap]


def merge_spans(spans):
    merged = []
    for a, b in sorted(spans):
        if merged and a <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], b)
        else:
            merged.append([a, b])
    return merged


def tidy_clips(raw, words, keep):
    clips = []
    for clip in raw:
        start, end = snap(clip["start"], words, "start"), snap(clip["end"], words, "end")
        if not MIN_CLIP <= end - start <= MAX_CLIP:
            continue
        if any(start < c["end"] and c["start"] < end for c in clips):
            continue
        cold = None
        if clip.get("cold_open_start") is not None and clip.get("cold_open_end") is not None:
            cs, ce = snap(clip["cold_open_start"], words, "start"), snap(clip["cold_open_end"], words, "end")
            if start + 1 < cs and ce <= end and 1.5 <= ce - cs <= 8:
                cold = list(breathe(cs, ce, words, 0.1, 0.3))
        start, end = breathe(start, end, words, LEAD, TAIL)
        skip = sorted([a, b] for a, b in clip.get("skip") or [] if start + 1 < a < b < end - 1)
        skip = [s for i, s in enumerate(skip) if i == 0 or s[0] > skip[i - 1][1]]
        if clip.get("max_seconds"):
            fitted = fit_end(start, end, skip, cold, words, clip["max_seconds"])
            if cold and cold[1] > fitted:  # the teaser's line would be cut: drop the teaser, keep the payoff
                cold, fitted = None, fit_end(start, end, skip, None, words, clip["max_seconds"])
            end, skip = fitted, [s for s in skip if s[1] < fitted - 1]
        clips.append({**clip, "start": start, "end": end, "cold_open": cold, "skip": skip, "score": rank_score(clip)})
    clips.sort(key=lambda c: -c["score"])
    return clips[:keep]


SCORES = ("hook", "standalone", "payoff", "emotion")
TEXTS = ("title", "hook_text", "reason")


def moment_problems(raw):
    problems = []
    for i, clip in enumerate(raw, 1):
        for field in ("start", "end"):
            if not isinstance(clip.get(field), (int, float)):
                problems.append(f"moment {i}: {field} must be a number of seconds")
        for field in TEXTS:
            if not isinstance(clip.get(field), str) or not clip[field].strip():
                problems.append(f"moment {i}: {field} is missing")
        for field in SCORES:
            if clip.get(field) not in (1, 2, 3, 4, 5):
                problems.append(f"moment {i}: {field} must be a whole number from 1 to 5")
        emphasis = clip.get("emphasis", [])
        if not isinstance(emphasis, list) or not all(isinstance(w, str) for w in emphasis):
            problems.append(f"moment {i}: emphasis must be a list of words")
        for field in ("speaker_name", "speaker_role"):
            if clip.get(field) is not None and not isinstance(clip[field], str):
                problems.append(f"moment {i}: {field} must be text")
        skip = clip.get("skip")
        if skip is not None and (not isinstance(skip, list) or not all(
                isinstance(s, list) and len(s) == 2 and all(isinstance(t, (int, float)) for t in s) and s[0] < s[1] for s in skip)):
            problems.append(f"moment {i}: skip must be a list of [from, to] seconds pairs")
        accent = clip.get("hook_accent")
        if accent is not None and (not isinstance(accent, list) or not all(isinstance(w, str) for w in accent)):
            problems.append(f"moment {i}: hook_accent must be a list of words")
        parts = clip.get("hook_parts")
        if parts is not None and (not isinstance(parts, dict) or not all(isinstance(parts.get(k, ""), str) for k in ("kicker", "big", "punch"))):
            problems.append(f"moment {i}: hook_parts must hold kicker, big and punch as text")
        for key in ("stat", "deal"):
            value = clip.get(key)
            if value is None:
                continue
            if not isinstance(value, dict) or not isinstance(value.get("at"), (int, float)) or not isinstance(value.get("value"), str):
                problems.append(f"moment {i}: {key} needs at (seconds in the source) and value (text)")
            elif not clip.get("start", 0) <= value["at"] <= clip.get("end", 0):
                problems.append(f"moment {i}: {key} at must fall between start and end")
    return problems


def load_moments(workdir):
    path = workdir / "moments.json"
    if not path.exists():
        sys.exit(f"{path} does not exist. Pick the moments first.")
    raw = json.loads(path.read_text(encoding="utf-8"))
    raw = raw.get("clips", []) if isinstance(raw, dict) else raw
    problems = moment_problems(raw)
    if problems:
        sys.exit("moments.json needs fixing:\n" + "\n".join(problems))
    return raw


def probe_size(video):
    out = run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height",
               "-of", "csv=p=0", str(video)]).stdout.strip()
    width, height = out.split(",")[:2]
    return int(width), int(height)


def shot_cuts(video, start, end):
    out = subprocess.run(["ffmpeg", "-hide_banner", "-ss", f"{start}", "-t", f"{end - start}", "-i", str(video),
                          "-vf", "scale=320:-2,select='gt(scene,0.3)',showinfo", "-an", "-f", "null", "-"],
                         capture_output=True, text=True, encoding="utf-8", errors="replace").stderr
    return [start + float(t) for t in re.findall(r"pts_time:([\d.]+)", out)]


def face_detector():
    import cv2

    if not FACE_MODEL.exists():
        FACE_MODEL.parent.mkdir(parents=True, exist_ok=True)
        urllib.request.urlretrieve(FACE_MODEL_URL, FACE_MODEL)
    return cv2.FaceDetectorYN.create(str(FACE_MODEL), "", (320, 320), 0.7)


def face_center(capture, detector, start, end, focus=None):
    import cv2

    centers = []
    for fraction in (0.2, 0.5, 0.8):
        capture.set(cv2.CAP_PROP_POS_MSEC, (start + (end - start) * fraction) * 1000)
        ok, frame = capture.read()
        if not ok:
            continue
        scale = 640 / frame.shape[1]
        small = cv2.resize(frame, (640, round(frame.shape[0] * scale)))
        detector.setInputSize((small.shape[1], small.shape[0]))
        _, faces = detector.detect(small)
        faces = [f for f in faces if f[2] >= small.shape[1] * MIN_FACE] if faces is not None else []
        if faces:
            near = (lambda f: -abs((f[0] + f[2] / 2) / small.shape[1] - focus)) if focus else (lambda f: f[2] * f[3])
            x, _, w, h = max(faces, key=near)[:4]
            centers.append((x + w / 2) / scale)
    return statistics.median(centers) if centers else None


def face_share(video, detector, start, end, samples=10):
    """Share of frames sampled across start to end that show a face; slides and wide shots score low."""
    import cv2

    capture = cv2.VideoCapture(str(video))
    seen = read = 0
    for k in range(samples):
        capture.set(cv2.CAP_PROP_POS_MSEC, (start + (end - start) * (k + 0.5) / samples) * 1000)
        ok, frame = capture.read()
        if not ok:
            continue
        read += 1
        small = cv2.resize(frame, (640, round(frame.shape[0] * 640 / frame.shape[1])))
        detector.setInputSize((small.shape[1], small.shape[0]))
        _, faces = detector.detect(small)
        seen += any(f[2] >= small.shape[1] * MIN_FACE for f in (faces if faces is not None else []))
    capture.release()
    return seen / read if read else 0.0


def speaker_share(workdir, moment):
    """face_share over a picked moment, read from its fetched section."""
    meta = json.loads((workdir / "meta.json").read_text(encoding="utf-8"))
    video, offset = video_section(workdir, meta, {**moment, "cold_open": moment.get("cold_open")}, None)
    return face_share(video, face_detector(), moment["start"] - offset, moment["end"] - offset)


def main_face(faces):
    """The speaker is the biggest face; a hand or a second person must not stretch the span the hook avoids."""
    return max(faces, key=lambda f: f[2] * f[3]) if len(faces) else None


def face_span(video, detector):
    import cv2

    capture = cv2.VideoCapture(str(video))
    spans = []
    for t in (0.3, 1.0, 1.7, 2.4):
        capture.set(cv2.CAP_PROP_POS_MSEC, t * 1000)
        ok, frame = capture.read()
        if not ok:
            continue
        scale = 640 / frame.shape[1]
        small = cv2.resize(frame, (640, round(frame.shape[0] * scale)))
        detector.setInputSize((small.shape[1], small.shape[0]))
        _, faces = detector.detect(small)
        face = main_face([f for f in (faces if faces is not None else []) if f[2] >= small.shape[1] * MIN_FACE])
        if face is not None:
            x, y, w, h = face[:4]
            spans.append((y / scale, (y + h) / scale))
    capture.release()
    return [round(min(a for a, _ in spans)), round(max(b for _, b in spans))] if spans else None


def crop_x(center, src_w, crop_w):
    if center is None:
        center = src_w / 2
    return int(max(0, min(src_w - crop_w, center - crop_w / 2)))


def track_shot(capture, detector, start, end, focus, src_w, crop_w, shift):
    """Crop positions across one shot, sampled every ~2.5s so the crop follows a speaker who moves.
    Returns (points, found) where found says whether any face was seen in the shot."""
    n = max(1, round((end - start) / 2.5))
    times = [start + (end - start) * k / n for k in range(n + 1)]
    centers = [face_center(capture, detector, max(start, t - 0.15), min(end, t + 0.15), focus) for t in times]
    known = [c for c in centers if c is not None]
    if not known:
        centers = [None] * len(centers)
    else:
        fallback = statistics.median(known)
        centers = [fallback if c is None else c for c in centers]
        centers = [statistics.median(centers[max(0, i - 1):i + 2]) for i in range(len(centers))]
    return [(shift + t, crop_x(c, src_w, crop_w)) for t, c in zip(times, centers)], bool(known)


def crop_expression(points):
    """Piecewise linear crop x over time; equal timestamps are hard cuts between shots."""
    expr = str(points[-1][1])
    for (t0, x0), (t1, x1) in reversed(list(zip(points, points[1:]))):
        if t1 - t0 < 0.01:
            continue
        segment = str(x0) if x0 == x1 else f"{x0}+({x1}-{x0})*(t-{t0:.3f})/{t1 - t0:.3f}"
        expr = f"if(lt(t,{t1:.3f}),{segment},{expr})"
    return expr


def pieces_for(clip):
    main, at = [], clip["start"]
    for a, b in sorted(clip.get("skip") or []):
        main.append((at, a))
        at = b
    main.append((at, clip["end"]))
    if clip.get("intro"):
        return [(clip["start"] - clip["intro"], clip["start"])] + main
    return ([tuple(clip["cold_open"])] if clip["cold_open"] else []) + main


def ass_time(t):
    t = max(0.0, t)
    return f"{int(t // 3600)}:{int(t % 3600 // 60):02d}:{t % 60:05.2f}"


def caption_chunks(words, size=6, gap=0.6):
    chunks, current = [], []
    for word in words:
        if current and (len(current) == size or word["start"] - current[-1]["end"] > gap or word.get("cut")
                        or current[-1]["word"][-1:] in ".?!"):
            chunks.append(current)
            current = []
        current.append(word)
    if current:
        chunks.append(current)
    return chunks


def ass_escape(text):
    return text.replace("\\", "").replace("{", "(").replace("}", ")")


def clip_timeline(clip, words):
    timeline, offset = [], 0.0
    for i, (a, b) in enumerate(pieces_for(clip)):
        if i == 0 and clip.get("intro"):
            offset += b - a
            continue
        piece = [{"word": w["word"], "start": w["start"] - a + offset, "end": min(w["end"], b) - a + offset}
                 for w in words if a - 0.05 <= w["start"] < b]
        if piece and timeline:
            piece[0]["cut"] = True
        timeline += piece
        offset += b - a
    return timeline


def build_ass(clip, words):
    timeline = clip_timeline(clip, words)
    events = [f"Dialogue: 1,{ass_time(0)},{ass_time(HOOK_SECONDS)},Hook,,0,0,0,,{ass_escape(clip['hook_text'])}"]
    captions = []
    for chunk in caption_chunks(timeline):
        for i, word in enumerate(chunk):
            text = " ".join(("{\\c&H0000E5FF&}" + ass_escape(w["word"]) + "{\\c&HFFFFFF&}") if j == i else ass_escape(w["word"])
                            for j, w in enumerate(chunk))
            captions.append((word["start"], word["end"], re.sub(r" (?=(\{[^}]*\})?[-'’])", "", text)))
    for (start, end, text), following in zip(captions, captions[1:] + [None]):
        if following:
            end = following[0] if following[0] - end < 0.4 else min(end + 0.15, following[0])
        events.append(f"Dialogue: 0,{ass_time(start)},{ass_time(end)},Caption,,0,0,0,,{text}")
    return f"""[Script Info]
ScriptType: v4.00+
PlayResX: {OUT_W}
PlayResY: {OUT_H}
WrapStyle: 0

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Caption,Poppins ExtraBold,88,&H00FFFFFF,&H00FFFFFF,&H00000000,&H64000000,0,0,0,0,100,100,0,0,1,6,0,2,80,80,560,1
Style: Hook,Poppins ExtraBold,70,&H00111111,&H00111111,&H00FFFFFF,&H00FFFFFF,0,0,0,0,100,100,0,0,3,20,0,8,90,90,300,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
""" + "\n".join(events) + "\n"


def frame_filter(src_w, src_h, crop_w, crop_h, steps, faces_seen):
    """A wide source is always cropped to the full 9:16, following the face where one was seen; never letterboxed."""
    if src_w / src_h > 9 / 16 + 0.01:
        return f"crop={crop_w}:{crop_h}:x='{crop_expression(steps)}':y=0,scale={OUT_W}:{OUT_H}"
    return f"scale={OUT_W}:{OUT_H}:force_original_aspect_ratio=increase,crop={OUT_W}:{OUT_H}"


def cut_graph(video, clip, detector, subtitles=None):
    import cv2

    src_w, src_h = probe_size(video)
    pieces = pieces_for(clip)
    focus = clip.get("focus_x")
    base = min(a for a, _ in pieces)
    parts, steps, offset, seen = [], [], 0.0, []
    capture = cv2.VideoCapture(str(video))
    crop_h = round(src_h * STYLE["keep_height"] / 2) * 2
    crop_w = min(src_w, round(crop_h * 9 / 16 / 2) * 2)
    for i, (a, b) in enumerate(pieces):
        fade_in = FADE_IN if i == 0 else JOIN_FADE
        fade_out = FADE_OUT if i == len(pieces) - 1 else JOIN_FADE
        quiet = "volume=0.12," if i == 0 and clip.get("intro") else ""
        parts.append(f"[0:v]trim=start={a - base:.3f}:end={b - base:.3f},setpts=PTS-STARTPTS[v{i}];"
                     f"[0:a]atrim=start={a - base:.3f}:end={b - base:.3f},asetpts=PTS-STARTPTS,{quiet}"
                     f"afade=t=in:st=0:d={fade_in},afade=t=out:st={max(0.0, b - a - fade_out):.3f}:d={fade_out}[a{i}]")
        bounds = [a] + [t for t in shot_cuts(video, a, b) if a + 0.3 < t < b - 0.3] + [b]
        for s, e in zip(bounds, bounds[1:]):
            points, found = track_shot(capture, detector, s, e, focus, src_w, crop_w, offset - a)
            seen.append(found)
            steps += points
        offset += b - a
    capture.release()

    joined = "".join(f"[v{i}][a{i}]" for i in range(len(pieces))) + f"concat=n={len(pieces)}:v=1:a=1[cv][ca]"
    frame = frame_filter(src_w, src_h, crop_w, crop_h, steps, seen)
    if not subtitles and clip.get("outro"):
        hold = clip["outro"]["seconds"]
        joined = joined.replace("[cv][ca]", "[cv][cj]") + f";[cj]apad=pad_dur={hold}[ca]"
        return ";".join(parts + [joined, f"[cv]{frame},setsar=1,tpad=stop_mode=clone:stop_duration={hold}[vo]"])
    if not subtitles:
        return ";".join(parts + [joined, f"[cv]{frame},setsar=1[vo]"])
    if not STYLE["watermark"]:
        return ";".join(parts + [joined, f"[cv]{frame},setsar=1,subtitles={subtitles}:fontsdir=.[vo]"])
    return ";".join(parts + [joined, f"[cv]{frame},setsar=1,subtitles={subtitles}:fontsdir=.[sv]",
                             f"movie={WATERMARK.name}[wm]", "[sv][wm]overlay=W-w-48:H-h-64[vo]"])


def cut(video, clip, graph, out, cwd, encoder=("-c:v", "libx264", "-preset", "veryfast", "-crf", "18")):
    start = min(a for a, _ in pieces_for(clip))
    run(["ffmpeg", "-y", "-ss", f"{start}", "-t", f"{clip['end'] - start}", "-i", str(video),
         "-filter_complex", graph, "-map", "[vo]", "-map", "[ca]",
         *encoder, "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart", str(out)], cwd=cwd)


def reel_data(clip, words, duration, face=None):
    timeline = clip_timeline(clip, words)
    groups, index = [], 0
    for chunk in caption_chunks(timeline):
        groups.append([index, index + len(chunk) - 1])
        index += len(chunk)
    name = (clip.get("speaker_name") or "").strip()
    return {
        "duration": duration,
        "cut": round(clip["cold_open"][1] - clip["cold_open"][0], 3) if clip["cold_open"] else None,
        "hook": clip["hook_text"],
        "hook_parts": clip.get("hook_parts"),
        "stat": card(clip, "stat"),
        "deal": card(clip, "deal"),
        "face": face,
        "emphasis": clip.get("emphasis") or [],
        "speaker": {"name": name, "role": (clip.get("speaker_role") or "").strip()} if name else None,
        "words": [{"t": w["word"], "s": round(max(0.0, w["start"]), 3), "e": round(w["end"], 3)} for w in timeline],
        "groups": groups,
        "intro": {"seconds": clip["intro"]} if clip.get("intro") else None,
        "outro": {"at": round(sum(b - a for a, b in pieces_for(clip)), 3), "seconds": clip["outro"]["seconds"],
                  "text": clip["outro"]["text"]} if clip.get("outro") else None,
        "cards": [{**c, "at": at} for c in clip.get("cards") or [] if (at := clip_time(clip, c["at"])) is not None],
        "joins": joins(clip),
        "hook_style": clip.get("hook_style") or "spotlight",
        "hook_accent": clip.get("hook_accent") or [],
        "brand_tag": clip.get("brand_tag") or "",
    }


def joins(clip):
    """Reel times of the jump cuts between pieces; a pre-roll running straight into the moment is no cut."""
    out, at, pieces = [], 0.0, pieces_for(clip)
    for (a, b), (c, _) in zip(pieces, pieces[1:]):
        at += b - a
        if abs(b - c) > 0.01:
            out.append(round(at, 3))
    return out


def hook_end(reel):
    """When v2.html's hook leaves and captions start (mirrors HOOK_END): a headline holds 2.5 s, or the cold open up to 3.5 s."""
    base = min(max(2.5, reel.get("cut") or 0), 3.5) if reel.get("hook_style") == "headline" else 1.85
    return min(max(base, (reel.get("intro") or {}).get("seconds", 0)), reel["duration"] - 0.4)


def hook_slam(reel):
    """When v2.html slams the hook: the big word's shake, else the punch line's (mirrors hookParts and buildHook)."""
    if reel.get("hook_style") == "headline":
        return 0.1  # the headline lands
    parts = reel.get("hook_parts")
    if not (parts and (parts.get("big") or parts.get("punch"))):
        words = str(reel.get("hook") or "").split()
        big = next((w for w in words if re.search(r"[0-9₹]", w)), "")
        parts = {"big": big, "punch": " ".join([w for w in words if w != big][-2:])}
    return 0.72 if parts.get("big") else 1.14 if parts.get("punch") else None


def card_times(reel):
    """When v2.html shows each context card (mirrors buildCards: after the hook, no overlaps)."""
    d = reel["duration"]
    gone = hook_end(reel)
    cap_end = reel["outro"]["at"] if reel.get("outro") else d
    shown = []
    for c in reel.get("cards") or []:
        if c.get("at") is None or c["at"] > cap_end - 1:
            continue
        at = max(gone + 0.1, c["at"])
        out = min(at + c.get("hold", 4), d - 0.05, cap_end)
        if not any(at < y + 0.2 and x < out + 0.2 for x, y in shown):
            shown.append((at, out))
    return [round(a, 3) for a, _ in shown]


@functools.cache
def sfx_seconds(name):
    return round(duration_of(SFX / f"{name}.mp3"), 3)


def sfx_tags(reel, total):
    """<audio> tracks for the sound design: whoosh on the hook, impact on its slam, pop per card, swoosh per cut."""
    slam = hook_slam(reel) if reel.get("hook") or reel.get("hook_parts") else None
    cues = ([("whoosh", 0.0)] + ([("impact", slam)] if slam is not None else [])
            + [("pop", t) for t in card_times(reel)] + [("swoosh", t) for t in reel.get("joins") or []])
    tags = []
    for i, (name, t) in enumerate(c for c in cues if c[1] < total - 0.1):
        tags.append(f'<audio id="sfx-{i}" src="sfx/{name}.mp3" data-start="{t}" '
                    f'data-duration="{min(sfx_seconds(name), round(total - t, 3))}" data-track-index="{20 + i}" '
                    f'data-volume="{SFX_VOLUME[name]}"></audio>')
    return "".join(tags)


def music_bed(src, reel, total, volume):
    """The music bed at a low base volume, ducked further while words are spoken (a HyperFrames volume lane)."""
    voice = [(0.0, reel["intro"]["seconds"])] if reel.get("intro") else []
    voice += [(reel["outro"]["at"], reel["outro"]["at"] + reel["outro"]["seconds"])] if reel.get("outro") else []
    spans = []
    for s, e in sorted(voice + [(w["s"], w["e"]) for w in reel["words"]]):
        if spans and s - spans[-1][1] < 0.5:
            spans[-1][1] = max(spans[-1][1], e)
        else:
            spans.append([s, e])
    low, points = round(volume * DUCK, 3), [{"t": 0, "v": volume}]
    for s, e in spans[:120]:  # ponytail: a lane holds 512 points; past 120 spans the bed stays at its last level
        points += [{"t": round(max(0.0, s - 0.15), 3), "v": volume}, {"t": round(s, 3), "v": low},
                   {"t": round(e, 3), "v": low}, {"t": round(e + 0.25, 3), "v": volume}]
    lane = json.dumps({"version": 1, "lanes": [{"target": "volume", "points": points}]})
    return (f'<audio id="music" src="{src}" data-start="0" data-duration="{total}" data-track-index="11" '
            f"data-volume=\"{volume}\" data-automation='{lane}'></audio>")


def channel_card(url):
    info = json.loads(run([*YTDLP, "--flat-playlist", "--playlist-items", "0", "-J", url]).stdout)
    avatar = next((t["url"] for t in info.get("thumbnails", []) if t.get("id") == "avatar_uncropped"), None)
    if not avatar:
        sys.exit(f"no channel avatar found for {url}; pass a logo file or image url to --end-screen")
    return avatar, info.get("channel") or info.get("uploader") or "", info.get("uploader_id") or ""


def download_image(url, folder):
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(request, timeout=30) as response:
        kind = response.headers.get_content_type()
        suffix = IMAGE_TYPES.get(kind) or Path(url.split("?")[0]).suffix.lower()
        if suffix not in IMAGE_TYPES.values():
            sys.exit(f"--end-screen {url} is not an image ({kind})")
        target = folder / f"end-logo{suffix}"
        target.write_bytes(response.read())
    return target


def end_screen(workdir):
    choice = END["choice"]
    if not choice:
        return None
    name, line, kind = END["name"], END["line"], "logo"
    if choice == "channel" or re.match(r"https?://(www\.|m\.)?youtube\.com/(@|channel/|c/|user/)", choice):
        if choice == "channel":
            info_file = workdir / "source-audio.info.json"
            choice = json.loads(info_file.read_text(encoding="utf-8")).get("channel_url") if info_file.exists() else None
            if not choice:
                sys.exit("--end-screen with no logo needs a YouTube video; pass a logo file or image url")
        choice, channel, handle = channel_card(choice)
        name, line, kind = name or channel, line or handle, "avatar"
    for old in workdir.glob("end-logo.*"):
        old.unlink()
    if Path(choice).expanduser().is_file():
        source = Path(choice).expanduser()
        if source.suffix.lower() not in IMAGE_TYPES.values():
            sys.exit(f"--end-screen {choice} is not an image (svg, png, jpg, webp or gif)")
        logo = workdir / f"end-logo{source.suffix.lower()}"
        shutil.copy(source, logo)
    elif choice.startswith(("http://", "https://")):
        logo = download_image(choice, workdir)
    else:
        sys.exit(f"--end-screen {choice} is neither a file nor a url")
    return {"logo": logo, "kind": kind, "name": name.strip(), "line": line.strip()}


def npx():
    return shutil.which("npx")


def node_ok():
    node = shutil.which("node")
    if not node or not npx():
        return False
    version = run([node, "--version"]).stdout.strip().lstrip("v")
    return int(version.split(".")[0]) >= 22


def rgb(colour):
    return ", ".join(str(int(colour.lstrip("#")[i:i + 2], 16)) for i in (0, 2, 4))


def _key(word):
    return re.sub(r"[^\w₹$%]", "", word.lower())


def accent_words(reel):
    """Headline words to colour: hook_accent, else emphasis words in the headline, else its numbers, else its longest word."""
    words = [_key(w) for w in str(reel.get("hook") or "").split()]
    pick = lambda options: [k for k in dict.fromkeys(_key(w) for o in options for w in o.split()) if k and k in words]
    found = pick(reel.get("hook_accent") or []) or pick(reel.get("emphasis") or []) or pick(
        [w for w in words if re.search(r"\d", w)]) or ([max(words, key=len)] if words else [])
    return found[:4]


def headline_markup(reel):
    """The headline hook: brand tag over the headline, accent words in runs that alternate hot and sun."""
    accent, spans, run = set(accent_words(reel)), [], -1
    words = str(reel.get("hook") or "").split()
    for i, w in enumerate(words):
        lit = _key(w) in accent
        if lit and (i == 0 or _key(words[i - 1]) not in accent):
            run += 1
        cls = f"hl-w hl-a{run % 2}" if lit else "hl-w"
        spans.append(f'<span class="{cls}">{html.escape(w)}</span>')
    tag = (f'<div id="hl-tag"><span id="hl-tag-text">{html.escape(reel["brand_tag"])}</span><span id="hl-rule"></span></div>'
           if reel.get("brand_tag") else "")
    return f'<div id="headline"><div id="hl-shade"></div><div id="hl-box">{tag}<div id="hl-text">{" ".join(spans)}</div></div></div>'


HEADLINE_FONT = '@font-face { font-family: "Anton"; src: url("fonts/Anton-Regular.ttf") format("truetype"); font-weight: 400; }'


def reel_page(reel, design, total, duration, music_tag, theme, watermark=False, sfx=False):
    data = json.dumps(reel, ensure_ascii=False)
    if sfx:
        music_tag += sfx_tags(reel, total)
    html = REEL_TEMPLATES[design].read_text(encoding="utf-8")
    html = html.replace("<!--__MUSIC__-->", music_tag).replace("__TOTAL__", f"{total}").replace("__DURATION__", f"{duration}").replace("<!--__DATA__-->", f"<script>window.__REEL_DATA__ = {data};</script>")
    html = html.replace("<!--__WATERMARK__-->", '<img id="wm" src="watermark.png" alt="" />' if watermark else "")
    headline = reel.get("hook_style") == "headline"
    html = html.replace("<!--__HEADLINE__-->", headline_markup(reel) if headline else "")
    if headline:
        html = html.replace("<style>", f"<style>\n      {HEADLINE_FONT}", 1)
    if theme:
        font = theme["font"]
        html = html.replace("#ff5a1f", theme["hot"]).replace("255, 90, 31", rgb(theme["hot"]))
        html = html.replace("#ffd23f", theme["sun"]).replace("255, 210, 63", rgb(theme["sun"]))
        html = html.replace('--display: "Bricolage Grotesque", sans-serif;', f'--display: "{font}", sans-serif;')
        html = html.replace('const FONT = "Bricolage Grotesque";', f'const FONT = "{font}";')
        if (FONTS / f"{font}-ExtraBold.ttf").exists():  # else the template's own @font-face stays
            html = html.replace("<style>", f'<style>\n      @font-face {{ font-family: "{font}"; src: url("fonts/{font}-ExtraBold.ttf") format("truetype"); font-weight: 800; }}', 1)
    return html


def render_styled(workdir, video, clip, words, name, detector, out, parallel, *, design, watermark, end, music, theme=None, voices=None, sfx=False):
    project = workdir / "reel" / name
    if project.exists():
        shutil.rmtree(project)
    (project / "fonts").mkdir(parents=True)
    for font in FONTS.glob("*.ttf"):
        shutil.copy(font, project / "fonts" / font.name)
    shutil.copy(WATERMARK, project / WATERMARK.name)
    if end:
        shutil.copy(end["logo"], project / end["logo"].name)
    if music:
        shutil.copy(music, project / ("music" + Path(music).suffix))
    if sfx:
        shutil.copytree(SFX, project / "sfx", ignore=shutil.ignore_patterns("*.md"))
    cut(video, clip, cut_graph(video, clip, detector), project / "base.mp4", project, fast_encoder())
    duration = round(duration_of(project / "base.mp4") - 0.05, 3)
    reel = reel_data(clip, words, duration, face_span(project / "base.mp4", detector))
    if end:
        reel["end"] = {"src": end["logo"].name, "kind": end["kind"], "name": end["name"], "line": end["line"], "seconds": END_SECONDS}
    total = round(duration + (END_SECONDS if end else 0), 3)
    music_tag = music_bed(f"music{Path(music).suffix}", reel, total, MUSIC["volume"]) if music else ""
    for track, (key, audio) in enumerate((voices or {}).items(), 12):
        start = reel[key]["at"] if key == "outro" else 0
        shutil.copy(audio, project / f"{key}{Path(audio).suffix}")
        music_tag += (f'<audio id="vo-{key}" src="{key}{Path(audio).suffix}" data-start="{start}" '
                      f'data-duration="{round(duration_of(audio), 3)}" data-track-index="{track}" data-volume="1"></audio>')
    html = reel_page(reel, design, total, duration, music_tag, theme, watermark, sfx)
    (project / "index.html").write_text(encoding="utf-8", data=html)
    command = [npx(), "--yes", HYPERFRAMES, "render", str(project), "-o", str(out),
               "--crf", "23", "--fps", "30", "--quiet"]
    if sys.platform == "win32" or JOBS == 1:
        command += ["--workers", "1"]
    elif parallel:
        command += ["--workers", "2"]
    done = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if done.returncode != 0 or not out.exists():
        sys.exit(f"hyperframes render failed for {name}:\n{(done.stderr or done.stdout)[-1500:]}")


def render_one(workdir, moment, out, *, theme=None, intro=None, outro=None, music=None, sfx=False,
               hook_style="spotlight", brand_tag=""):
    """One moment, design v2, no watermark, no end screen. Engine exits become errors callers can catch.
    Without an intro the moment's cold open (if any) plays first. Also writes out.jpg, the cover frame."""
    try:
        return _render_one(workdir, {**moment, "hook_style": hook_style, "brand_tag": brand_tag}, out,
                           theme=theme, intro=intro, outro=outro, music=music, sfx=sfx)
    except SystemExit as e:
        raise RuntimeError(str(e.code)) from None


def _render_one(workdir, moment, out, *, theme, intro, outro, music, sfx=False):
    meta = json.loads((workdir / "meta.json").read_text(encoding="utf-8"))
    words = all_words(json.loads((workdir / "transcript.json").read_text(encoding="utf-8")))
    clips = tidy_clips([moment], words, 1)
    if not clips:
        raise ValueError(f"moment {moment['start']}-{moment['end']} must be {MIN_CLIP:.0f} to {MAX_CLIP:.0f} seconds")
    clip = clips[0]
    voices = {}
    if intro:
        if clip["start"] < intro["seconds"] + 0.5:
            raise ValueError(f"moment starts too early for a {intro['seconds']}s intro")
        # set before the section lookup, so the section must cover the pre-roll too
        clip = {**clip, "intro": intro["seconds"], "cold_open": None}
        voices["intro"] = intro["audio"]
    words = english_words(workdir, meta.get("language", "en")) or words
    video, offset = video_section(workdir, meta, clip, find_stream(workdir, meta))
    clip, words = shifted(clip, words, offset)
    if outro:
        clip = {**clip, "outro": {"seconds": outro["seconds"], "text": outro["text"]}}
        voices["outro"] = outro["audio"]
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    render_styled(workdir, video, clip, words, out.stem, face_detector(), out, False,
                  design="v2", watermark=False, end=None, music=music, theme=theme, voices=voices, sfx=sfx)
    cover_frame(out, out.with_suffix(".jpg"))
    return out


COVER_AT = 1.3  # the publisher's thumb_offset; the headline is fully shown by then


def cover_frame(video, jpg, at=COVER_AT):
    run(["ffmpeg", "-y", "-v", "error", "-ss", f"{at}", "-i", str(video), "-frames:v", "1", "-q:v", "2", str(jpg)])
    return jpg


def render_basic(video, clip, words, name, detector, clip_dir):
    (clip_dir / f"{name}.ass").write_text(encoding="utf-8", data=build_ass(clip, words))
    for font in FONTS.glob("*.ttf"):
        shutil.copy(font, clip_dir / font.name)
    shutil.copy(WATERMARK, clip_dir / WATERMARK.name)
    cut(video, clip, cut_graph(video, clip, detector, subtitles=f"{name}.ass"), f"{name}.mp4", clip_dir)
    (clip_dir / f"{name}.ass").unlink()
    (clip_dir / WATERMARK.name).unlink()
    for font in clip_dir.glob("*.ttf"):
        font.unlink()


def clip_name(index, clip):
    return f"{index:02d}-{re.sub(r'[^a-z0-9]+', '-', clip['title'].lower()).strip('-')[:40] or 'clip'}"


def render(workdir, clip, words, index, styled, section, parallel):
    clip_dir = workdir / "clips"
    name = clip_name(index, clip)
    video, offset = section
    clip, words = shifted(clip, words, offset)
    detector = face_detector()
    if styled:
        render_styled(workdir, video, clip, words, name, detector, clip_dir / f"{name}.mp4", parallel,
                      design=STYLE["design"], watermark=STYLE["watermark"], end=END["screen"], music=MUSIC["file"])
    else:
        render_basic(video, clip, words, name, detector, clip_dir)
    log(f"done: {name}.mp4")
    return f"{name}.mp4"


def stamp(t):
    return f"{int(t // 60)}:{int(t % 60):02d}"


def write_review(workdir, meta, clips):
    cards = []
    for c in clips:
        at = f"{meta['url']}&t={int(c['start'])}s" if "?" in meta["url"] else meta["url"]
        cards.append(f"""<article>
<video src="{html.escape(c['file'])}" controls preload="metadata"></video>
<div><h2>{html.escape(c['title'])}</h2>
<p class="hook">{html.escape(c['hook_text'])}</p>
<p>{html.escape(c['reason'])}</p>
<p class="meta">Score {c['score']} of 25 · hook {c['hook']} · standalone {c['standalone']} · payoff {c['payoff']} · emotion {c['emotion']}</p>
<p class="meta"><a href="{html.escape(at)}">Source {stamp(c['start'])} to {stamp(c['end'])}</a>{' · cold open' if c['cold_open'] else ''}</p></div>
</article>""")
    (workdir / "clips" / "index.html").write_text(encoding="utf-8", data=f"""<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{html.escape(meta['title'])} clips</title>
<style>body{{font:15px/1.5 system-ui;margin:24px auto;max-width:980px;padding:0 16px;background:#f6f6f4;color:#161616}}
article{{display:flex;gap:20px;background:#fff;border-radius:14px;padding:16px;margin:16px 0}}
video{{width:240px;aspect-ratio:9/16;border-radius:10px;background:#000;flex:none}}
h2{{margin:0 0 6px;font-size:18px}}.hook{{font-weight:700}}.meta{{color:#666;font-size:13px}}
@media(max-width:600px){{article{{flex-direction:column}}video{{width:100%}}}}</style>
<h1>{html.escape(meta['title'])}</h1>{''.join(cards)}""")


def duration_of(video):
    return float(run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(video)]).stdout)


def prepare(source):
    workdir, video, meta = fetch(source)
    transcript = transcribe(workdir, video, meta)
    lines = [f"[{s['start']:.1f}-{s['end']:.1f}] {s['text']}" for s in transcript["segments"]]
    (workdir / "transcript.txt").write_text(encoding="utf-8", data="\n".join(lines) + "\n")
    meta = {**meta, "duration": round(duration_of(video)), "transcript_source": transcript["source"],
            "language": transcript["language"]}
    (workdir / "meta.json").write_text(encoding="utf-8", data=json.dumps(meta, ensure_ascii=False, indent=2))
    if meta["url"] and not (workdir / "source.mp4").exists():
        cached_stream(workdir, meta["url"])
    print(json.dumps({"workdir": str(workdir), **meta, "segments": len(lines),
                      "transcript": str(workdir / "transcript.txt"), "moments_file": str(workdir / "moments.json")},
                     ensure_ascii=False, indent=2))


def planned(workdir, count):
    meta = json.loads((workdir / "meta.json").read_text(encoding="utf-8"))
    transcript = json.loads((workdir / "transcript.json").read_text(encoding="utf-8"))
    words = all_words(transcript)
    clips = tidy_clips(load_moments(workdir), words, count)
    if not clips:
        sys.exit(f"No usable moments: each needs {MIN_CLIP:.0f} to {MAX_CLIP:.0f} seconds and must not overlap another.")
    return meta, words, clips


def download_sections(workdir, meta, clips):
    from concurrent.futures import ThreadPoolExecutor

    stream = find_stream(workdir, meta)
    with ThreadPoolExecutor(len(clips)) as pool:
        return list(pool.map(lambda clip: video_section(workdir, meta, clip, stream), clips))


def fetch_sections(workdir, count):
    meta, _, clips = planned(workdir, count)
    download_sections(workdir, meta, clips)
    log(f"fetched the video for {len(clips)} clips")


@contextlib.contextmanager
def render_lock():
    """One render per machine at a time, so several videos in a batch do not all slow each other down."""
    work_root().mkdir(parents=True, exist_ok=True)
    with open(work_root() / ".render.lock", "a+") as handle:
        handle.seek(0)
        waiting = False
        while True:
            try:
                if sys.platform == "win32":
                    import msvcrt
                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError:
                if not waiting:
                    log("another render is running on this machine, waiting for it to finish")
                    waiting = True
                time.sleep(3)
        yield


def render_all(workdir, count, basic=False):
    meta, words, clips = planned(workdir, count)
    words = english_words(workdir, meta["language"]) or words
    old = workdir / "clips"
    if old.exists():
        shutil.rmtree(old)
    old.mkdir()
    styled = not basic and node_ok()
    if not basic and not styled:
        log("Node.js 22 or newer not found, so rendering basic captions. Install Node for the animated style.")
    if (workdir / "reel").exists():
        shutil.rmtree(workdir / "reel")
    END["screen"] = end_screen(workdir) if styled else None
    if END["choice"] and not styled:
        log("basic captions have no end screen, so it is left out")
    sections = download_sections(workdir, meta, clips)
    from concurrent.futures import ThreadPoolExecutor

    parallel = len(clips) > 1
    with render_lock():
        log(f"rendering {len(clips)} clips {'animated' if styled else 'with basic captions'}, {min(JOBS, len(clips))} at a time")
        with ThreadPoolExecutor(min(JOBS, len(clips))) as pool:
            files = list(pool.map(lambda pair: render(workdir, pair[1], words, pair[0], styled, sections[pair[0] - 1], parallel),
                                  enumerate(clips, 1)))
    for clip, file in zip(clips, files):
        clip["file"] = file
        clip["end_screen"] = bool(END["screen"])
    (workdir / "clips" / "clips.json").write_text(encoding="utf-8", data=json.dumps(clips, ensure_ascii=False, indent=2))
    write_review(workdir, meta, clips)
    print(json.dumps({"review_page": str(workdir / "clips" / "index.html"),
                      "clips": [{"file": str(workdir / "clips" / c["file"]), "title": c["title"], "score": c["score"],
                                 "seconds": round(sum(b - a for a, b in pieces_for(c)) + (END_SECONDS if c["end_screen"] else 0))}
                                for c in clips]}, ensure_ascii=False, indent=2))


def check(workdir):
    clips = json.loads((workdir / "clips" / "clips.json").read_text(encoding="utf-8"))
    folder = workdir / "check"
    folder.mkdir(exist_ok=True)
    sheets = []
    for clip in clips:
        video = workdir / "clips" / clip["file"]
        length = duration_of(video)
        cards = [c["at"] + 0.8 for c in (card(clip, key) for key in ("stat", "deal")) if c]
        ending = [length - 0.3] if clip.get("end_screen") else []
        times = [min(t, length - 0.1) for t in [1.3, *cards, length / 2, *ending]]
        inputs = [arg for t in times for arg in ("-ss", f"{t:.2f}", "-i", str(video))]
        graph = "".join(f"[{i}:v]scale=360:-2[f{i}];" for i in range(len(times)))
        graph += "".join(f"[f{i}]" for i in range(len(times))) + f"hstack=inputs={len(times)}"
        sheet = folder / f"{Path(clip['file']).stem}.jpg"
        run(["ffmpeg", "-v", "error", "-y", *inputs, "-filter_complex", graph, "-frames:v", "1", str(sheet)])
        sheets.append({"sheet": str(sheet), "seconds": [round(t, 1) for t in times]})
    print(json.dumps(sheets, ensure_ascii=False, indent=2))


def install_hint(tool):
    if sys.platform == "win32":
        return {"ffmpeg": "winget install Gyan.FFmpeg", "ffprobe": "winget install Gyan.FFmpeg", "yt-dlp": "winget install yt-dlp.yt-dlp"}[tool]
    return f"brew install {'ffmpeg' if tool.startswith('ff') else tool}"


def doctor():
    ok = True
    for tool in ("ffmpeg", "ffprobe", "yt-dlp"):
        found = shutil.which(tool)
        print(f"{tool}: {'ok' if found else 'missing (' + install_hint(tool) + ')'}")
        ok = ok and bool(found)
    if shutil.which("ffmpeg"):
        filters = run(["ffmpeg", "-hide_banner", "-filters"]).stdout
        has_ass = " subtitles " in filters
        print(f"ffmpeg captions (libass): {'ok' if has_ass else 'missing, install a full ffmpeg build (' + install_hint('ffmpeg') + ')'}")
        ok = ok and has_ass
    node_hint = "winget install OpenJS.NodeJS.LTS" if sys.platform == "win32" else "brew install node"
    print(f"node 22+ (animated clips): {'ok' if node_ok() else 'missing (' + node_hint + '), clips fall back to basic captions'}")
    print(f"clips folder: {work_root()}")
    sys.exit(0 if ok else 1)


def workdir_for(value):
    path = Path(value).expanduser().resolve()
    return path if path.is_dir() else work_root() / value


def main():
    parser = argparse.ArgumentParser(description="Cut vertical clips with captions from a long video.")
    commands = parser.add_subparsers(dest="command", required=True)
    step = commands.add_parser("prepare", help="download the video and write transcript.txt")
    step.add_argument("source", help="YouTube url or local video file")
    step = commands.add_parser("render", help="render the moments in moments.json")
    step.add_argument("workdir", help="the workdir prepare printed, or the video id")
    step.add_argument("-n", "--count", type=int, default=3, help="clips to render")
    step.add_argument("--basic", action="store_true", help="plain burned in captions instead of the animated template")
    step.add_argument("--music", help="an audio file mixed quietly under the speech (animated clips only)")
    step.add_argument("--music-volume", type=float, default=0.12, help="music level, 0 to 1 (default 0.12)")
    step.add_argument("--design", choices=sorted(REEL_TEMPLATES), default="v2", help="v2 Spotlight (default) or v1 the original white card look")
    step.add_argument("--watermark", choices=("on", "off"),
                      help="the musubiclip.com watermark; on by default for v1, off for v2")
    step.add_argument("--keep-height", type=float, default=1.0,
                      help="share of the source height to keep from the top, e.g. 0.86 to crop off burned in subtitles")
    step.add_argument("--end-screen", nargs="?", const="channel", metavar="LOGO",
                      help="add an animated end screen (v2): alone uses this video's YouTube channel avatar; "
                           "a YouTube channel url uses that channel's; else a logo file or image url")
    step.add_argument("--end-name", default="", help="the big name on the end screen (default the channel name)")
    step.add_argument("--end-line", default="", help="the line under it, such as a handle or website (default the @handle)")
    step = commands.add_parser("fetch", help="download the video for the moments ahead of render, in the background")
    step.add_argument("workdir", help="the workdir prepare printed, or the video id")
    step.add_argument("-n", "--count", type=int, default=3, help="clips you will render")
    step = commands.add_parser("check", help="one contact sheet per rendered clip: the hook, each card and the middle")
    step.add_argument("workdir", help="the workdir prepare printed, or the video id")
    step = commands.add_parser("english", help="list transcript lines inside moments.json that english.json does not translate yet")
    step.add_argument("workdir", help="the workdir prepare printed, or the video id")
    commands.add_parser("doctor", help="check the tools and key are in place")
    args = parser.parse_args()

    if args.command == "prepare":
        prepare(args.source)
    elif args.command == "render":
        if args.music:
            if not Path(args.music).is_file():
                sys.exit(f"music file not found: {args.music}")
            MUSIC.update(file=str(Path(args.music).resolve()), volume=args.music_volume)
        if not 0.5 <= args.keep_height <= 1:
            sys.exit("--keep-height must be between 0.5 and 1")
        watermark = args.watermark == "on" if args.watermark else args.design == "v1"
        STYLE.update(design=args.design, keep_height=args.keep_height, watermark=watermark)
        if args.end_screen and args.design != "v2":
            sys.exit("--end-screen needs --design v2")
        END.update(choice=args.end_screen, name=args.end_name, line=args.end_line)
        render_all(workdir_for(args.workdir), args.count, args.basic)
    elif args.command == "fetch":
        fetch_sections(workdir_for(args.workdir), args.count)
    elif args.command == "check":
        check(workdir_for(args.workdir))
    elif args.command == "english":
        print("\n".join(untranslated(workdir_for(args.workdir))) or "[]")
    else:
        doctor()


if __name__ == "__main__":
    main()
