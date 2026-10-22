"""Script first reels: Claude writes, Polly speaks, stock or CC footage underneath, the engine renders."""
import json
import os
import random
import subprocess
import tempfile
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from engine import clipper
from pages import config, store, voice, writing
from pages.db import QUEUE_LOW, queue_size
from pages.db import event as db_event

TAIL = 1.0
CC_WAIT_DAYS = 3
CC_SEARCH = "https://www.youtube.com/results?search_query={}&sp=EgIwAQ%253D%253D"


@dataclass
class Shot:
    provider: str
    id: str
    download_url: str
    page_url: str
    author: str
    licence: str
    seconds: float


def _get_json(url: str, headers: dict | None = None) -> dict:
    with urllib.request.urlopen(urllib.request.Request(url, headers=headers or {}), timeout=30) as r:
        return json.load(r)


def _pick(files: list[tuple[int, str]]) -> str | None:
    files = [f for f in files if f[1]]
    tall = [f for f in files if f[0] >= 1080]
    return (min(tall) if tall else max(files, default=(0, None)))[1]


def _pexels(query: str) -> list[Shot]:
    key = os.environ.get("PEXELS_KEY")
    if not key:
        return []
    q = urllib.parse.urlencode({"query": query, "orientation": "portrait", "per_page": 15})
    data = _get_json(f"https://api.pexels.com/videos/search?{q}", {"Authorization": key})
    return [Shot("pexels", str(v["id"]), _pick([(f.get("height") or 0, f.get("link")) for f in v["video_files"]]),
                 v["url"], v["user"]["name"], "Pexels License", v["duration"]) for v in data.get("videos", [])]


def _pixabay(query: str) -> list[Shot]:
    key = os.environ.get("PIXABAY_KEY")
    if not key:
        return []
    q = urllib.parse.urlencode({"key": key, "q": query, "safesearch": "true", "per_page": 20})
    data = _get_json(f"https://pixabay.com/api/videos/?{q}")
    return [Shot("pixabay", str(h["id"]), _pick([(f.get("height") or 0, f.get("url")) for f in h["videos"].values()]),
                 h["pageURL"], h["user"], "Pixabay Content License", h["duration"]) for h in data.get("hits", [])]


def search_footage(query: str, seconds: float, used: set[str]) -> Shot | None:
    for provider in (_pexels, _pixabay):
        for shot in provider(query):
            if shot.download_url and shot.seconds >= seconds and f"{shot.provider}:{shot.id}" not in used:
                return shot
    return None


def beat_spans(words: list[dict], beats: list[writing.Beat]) -> list[tuple[float, float]]:
    starts, i = [], 0
    for beat in beats:
        starts.append(0.0 if not starts else words[min(i, len(words) - 1)]["start"])
        i += len(beat.line.split())
    return list(zip(starts, starts[1:] + [words[-1]["end"]]))


def montage(shots: list[Path], spans, voice_mp3: Path, out: Path) -> Path:
    lengths = [b - a for a, b in spans]
    lengths[-1] += TAIL
    cmd, graph = ["ffmpeg", "-y", "-v", "error"], []
    for i, (shot, length) in enumerate(zip(shots, lengths)):
        cmd += ["-i", str(shot)]
        # tpad holds the last frame if a shot runs short
        graph.append(f"[{i}:v]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,setsar=1,fps=30,"
                     f"tpad=stop_mode=clone:stop_duration={length:.3f},trim=duration={length:.3f},setpts=PTS-STARTPTS[v{i}]")
    graph.append("".join(f"[v{i}]" for i in range(len(shots))) + f"concat=n={len(shots)}:v=1:a=0[v]")
    cmd += ["-i", str(voice_mp3), "-filter_complex", ";".join(graph), "-map", "[v]", "-map", f"{len(shots)}:a",
            "-af", "apad", "-t", f"{sum(lengths):.3f}", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", str(out)]
    out.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(cmd, check=True, capture_output=True)
    return out


def _download(url: str, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"}), timeout=120) as r:
        path.write_bytes(r.read())
    return path


def _used(db, page: str) -> set[str]:
    used = set()
    for credits, script in db.execute("select credits, script from clips where page = ?", (page,)):
        shots = json.loads(credits or "[]") + json.loads(script or "{}").get("shots", [])
        used |= {f"{c['provider']}:{c['id']}" for c in shots if isinstance(c, dict)}  # clip reels credit strings
    return used


def _set(db, clip_id: int, **cols) -> None:
    db.execute(f"update clips set {', '.join(f'{k} = ?' for k in cols)} where id = ?", [*cols.values(), clip_id])
    db.commit()


def make_reel(db, cfg, page) -> int:
    clip_id = db.execute("insert into clips (page, kind, status, created_at, attempts) values (?, 'script', 'planned', ?, 0)",
                         (page.handle, datetime.now(UTC).isoformat())).lastrowid
    db.commit()
    try:
        ideas = [json.loads(s)["idea"] for (s,) in
                 db.execute("select script from clips where page = ? and script is not null", (page.handle,))]
        script = writing.write_script(page, ideas)
        _set(db, clip_id, script=json.dumps(script.model_dump()))
        if not (os.environ.get("PEXELS_KEY") or os.environ.get("PIXABAY_KEY")):
            db_event(db, page.handle, "no_stock_keys", "using Creative Commons footage")
        tmp = config.HOME / "tmp" / f"script-{clip_id}"
        tmp.mkdir(parents=True, exist_ok=True)
        words, seconds = voice.speak(" ".join(b.line for b in script.beats), page.voice, tmp / "voice.mp3")
        if not 18 <= seconds <= 50:
            raise ValueError(f"script length {seconds:.0f} s, needs 18 to 50")
        # kept in the store so a reel waiting for CC footage needs no second Polly call
        store.put(f"work/script-{clip_id}/voice.mp3", tmp / "voice.mp3")
        spans = beat_spans(words, script.beats)
        used, shots = _used(db, page.handle), []
        for i, (beat, (a, b)) in enumerate(zip(script.beats, spans)):
            shot = search_footage(beat.shot_query, b - a, used)
            if shot:
                used.add(f"{shot.provider}:{shot.id}")
                shots.append(asdict(shot))
            else:
                shots.append({"provider": "cc", "id": f"{clip_id}-{i}", "query": beat.shot_query,
                              "seconds": round(b - a + (TAIL if i == len(spans) - 1 else 0), 2)})
        _set(db, clip_id, script=json.dumps({**script.model_dump(), "words": words, "seconds": seconds, "shots": shots}),
             status="waiting_footage")
        _finish(db, page, clip_id)
    except Exception as e:
        _set(db, clip_id, status="failed", reason=str(e))
    return clip_id


def _finish(db, page, clip_id: int) -> None:
    """Render a waiting reel once all its footage is in; leave it waiting otherwise."""
    data = json.loads(db.execute("select script from clips where id = ?", (clip_id,)).fetchone()[0])
    shots = data["shots"]
    have = [s["provider"] != "cc" or store.exists(f"footage/cc/{s['id']}.mp4") for s in shots]
    none = [s["provider"] == "cc" and store.exists(f"footage/cc/{s['id']}.none") for s in shots]
    if not all(h or n for h, n in zip(have, none)):
        return
    if not any(have):
        raise ValueError("no footage for any beat")
    # a beat with no CC match reuses the nearest beat with footage: previous first, else next
    n = len(shots)
    shots = [shots[next(j for j in [*range(i, -1, -1), *range(i + 1, n)] if have[j])] for i in range(n)]
    script = writing.Script(**{k: data[k] for k in writing.Script.model_fields})
    words, seconds = data["words"], data["seconds"]
    tmp = config.HOME / "tmp" / f"script-{clip_id}"
    mp3 = store.get(f"work/script-{clip_id}/voice.mp3", tmp / "voice.mp3")
    paths, credits = [], []
    got = {}  # shot id -> local path; a reused shot is fetched and credited once
    for i, s in enumerate(shots):
        if s["id"] in got:
            paths.append(got[s["id"]])
            continue
        if s["provider"] == "cc":
            got[s["id"]] = store.get(f"footage/cc/{s['id']}.mp4", tmp / f"shot-{i}.mp4")
            info = store.get_json(f"footage/cc/{s['id']}.json")
            credits.append({**s, **info, "credit": f"Footage: {info['author']} (CC BY) {info['page_url']}"})
        else:
            got[s["id"]] = _download(s["download_url"], tmp / f"shot-{i}.mp4")
            credits.append({**s, "credit": f"Footage: {s['author']} / {s['provider']}"})
        paths.append(got[s["id"]])
    video = montage(paths, beat_spans(words, script.beats), mp3, tmp / "montage.mp4")

    workdir = config.HOME / "work" / f"script-{clip_id}"
    workdir.mkdir(parents=True, exist_ok=True)
    (workdir / "meta.json").write_text(json.dumps({"title": script.title, "url": "", "path": str(video),
                                                   "duration": seconds + TAIL, "language": "en",
                                                   "transcript_source": "polly"}))
    (workdir / "transcript.json").write_text(json.dumps({"language": "en", "source": "polly",
                                                         "segments": clipper.group_segments(words)}))
    moment = {"start": 0.0, "end": seconds, "title": script.title, "hook_text": script.hook_text,
              "reason": script.idea, "emphasis": [], "hook": 3, "standalone": 3, "payoff": 3, "emotion": 3}
    (workdir / "moments.json").write_text(json.dumps([moment]))
    music = None
    if page.music:
        key = random.choice(page.music)
        music = store.get(key, tmp / Path(key).name)
    os.environ["MUSUBI_CLIPS_OFFLINE"] = "1"
    out = clipper.render_one(workdir, moment, tmp / "reel.mp4", theme=page.theme, music=music)
    file_key = f"clips/{clip_id}.mp4"
    store.put(file_key, out)

    previous = [c for (c,) in db.execute("select caption from clips where page = ? and caption is not null", (page.handle,))]
    caption = writing.write_caption(page, script.idea, [c["credit"] for c in credits], previous)
    _set(db, clip_id, credits=json.dumps(credits), file_key=file_key, caption=caption, start=0.0, end=seconds,
         moment=json.dumps(moment), status="draft")


def _cc_jobs(db) -> list[dict]:
    jobs = []
    for (s,) in db.execute("select script from clips where status = 'waiting_footage' order by id"):
        jobs += [{"key": x["id"], "query": x["query"], "seconds": x["seconds"]} for x in json.loads(s)["shots"]
                 if x["provider"] == "cc" and not store.exists(f"footage/cc/{x['id']}.mp4")
                 and not store.exists(f"footage/cc/{x['id']}.none")]
    return jobs


def step(db, cfg) -> None:
    for page in cfg.pages.values():
        if page.pipeline != "script":
            continue
        too_old = (datetime.now(UTC) - timedelta(days=CC_WAIT_DAYS)).isoformat()
        for clip_id, created in db.execute("select id, created_at from clips where page = ? and status = 'waiting_footage'",
                                           (page.handle,)).fetchall():
            try:
                _finish(db, page, clip_id)
                still = db.execute("select status from clips where id = ?", (clip_id,)).fetchone()[0] == "waiting_footage"
                if still and created < too_old:
                    raise ValueError(f"no CC footage after {CC_WAIT_DAYS} days")
            except Exception as e:
                _set(db, clip_id, status="failed", reason=str(e))
        # one waiting reel per page, so a sleeping Mac doesn't pile up Claude and Polly calls
        waiting = db.execute("select 1 from clips where page = ? and status = 'waiting_footage'", (page.handle,)).fetchone()
        # a reel that failed in the last hour (missing keys, Polly down) waits, or every run spends an Opus call
        recent = db.execute("select 1 from clips where id = (select max(id) from clips where page = ? and "
                            "kind = 'script') and status = 'failed' and created_at > ?",
                            (page.handle, (datetime.now(UTC) - timedelta(hours=1)).isoformat())).fetchone()
        if not waiting and not recent and queue_size(db, page.handle) < QUEUE_LOW:
            make_reel(db, cfg, page)
    store.put_json("jobs/cc.json", _cc_jobs(db))


def _cc_search(query: str, seconds: float) -> dict | None:
    url = CC_SEARCH.format(urllib.parse.quote_plus(query))
    # --ignore-errors skips age-restricted/unavailable results; yt-dlp then exits 1 but still prints the JSON
    r = subprocess.run(["yt-dlp", "-J", "--ignore-errors", "--playlist-end", "10", url], capture_output=True, text=True)
    try:
        found = json.loads(r.stdout)
    except json.JSONDecodeError:
        raise RuntimeError(f"yt-dlp search failed ({r.returncode}): {r.stderr.strip()[-300:]}") from None
    return next((e for e in found.get("entries") or [] if e and "Creative Commons" in (e.get("license") or "")
                 and (e.get("duration") or 0) >= seconds + 4), None)


def fetch_cc(job: dict) -> bool:
    """Mac side: find a Creative Commons YouTube video for one beat and upload its middle section."""
    key, seconds = job["key"], float(job["seconds"])
    e = None
    for query in dict.fromkeys([job["query"], " ".join(job["query"].split()[:2])]):  # full, then simpler
        e = _cc_search(query, seconds)
        if e:
            break
    if not e:
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "none").write_text("")
            store.put(f"footage/cc/{key}.none", Path(tmp) / "none")
        return False
    start = e["duration"] / 2 - seconds / 2
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / f"{key}.mp4"
        subprocess.run(["yt-dlp", "-f", "bv*[ext=mp4]/bv*/b", "--download-sections", f"*{start:.1f}-{start + seconds:.1f}",
                        "--merge-output-format", "mp4", "-o", str(out), e["webpage_url"]],
                       capture_output=True, text=True, check=True)
        store.put(f"footage/cc/{key}.mp4", out)
    store.put_json(f"footage/cc/{key}.json", {"page_url": e["webpage_url"], "author": e.get("uploader") or "",
                                              "licence": e["license"]})
    return True
