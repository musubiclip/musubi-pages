"""Animal clips (billikalesh): Creative Commons YouTube videos, moments picked by Claude from contact sheets.

No speech, so no transcript: Claude looks at frames. The reel gets a hook, 1 to 2 context cards and music.
"""
import json
import os
import random
import subprocess
from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel, Field

from pages import config, llm, store, writing  # config first: it sets MUSUBI_CLIPS_DIR for the engine
from pages.clips_pipeline import _pull
from pages.db import QUEUE_LOW, event, queue_size
from pages.script_pipeline import _cc_search, _video_seconds
from engine import clipper

SOURCE = "cc_youtube"
VIDEO_MIN, VIDEO_MAX = 30, 20 * 60
CLIP_MIN, CLIP_MAX = 15, 45
EVERY = 2.0  # seconds between contact sheet frames, stretched for long videos
TILE, MAX_SHEETS = 4, 12  # 4x4 frames a sheet


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _pages(cfg):
    return [p for p in cfg.pages.values() if p.pipeline == "animals" and p.active]


def _set(db, row, status, note=None) -> None:
    db.execute("update source_videos set status = ?, note = coalesce(?, note) where id = ?", (status, note, row["id"]))
    db.commit()


# --- jobs for the Mac, and what it sends back ---

def write_jobs(db, cfg) -> None:
    jobs, used = [], [v for (v,) in db.execute("select video_id from source_videos")]
    for page in _pages(cfg):
        busy = db.execute("select 1 from source_videos where page = ? and status = 'downloaded'", (page.handle,)).fetchone()
        if busy or not page.queries or queue_size(db, page.handle) >= QUEUE_LOW:
            continue
        # every search so far, found or not, moves the rotation on
        tries = (db.execute("select count(*) from source_videos where page = ? and source_id = ?",
                            (page.handle, SOURCE)).fetchone()[0]
                 + db.execute("select count(*) from events where page = ? and kind = 'animals_none'",
                              (page.handle,)).fetchone()[0])
        jobs.append({"page": page.handle, "query": page.queries[tries % len(page.queries)], "skip": used})
    store.put_json("jobs/animals.json", jobs)


def take_inbox(db, cfg) -> None:
    for key in store.keys("inbox/animals/"):
        v = store.get_json(key)
        if v.get("none"):
            event(db, v["page"], "animals_none", f"no Creative Commons video for {v['query']!r}")
        else:
            db.execute("insert or ignore into source_videos (source_id, page, video_id, url, title, status, note, "
                       "created_at) values (?, ?, ?, ?, ?, 'downloaded', ?, ?)",
                       (SOURCE, v["page"], v["video_id"], v["url"], v["title"],
                        f"{v['license']} · {v['channel']} · {v['url']}", _now()))
        store.delete(key)
    db.commit()


def fetch_animals(job: dict) -> bool:
    """Mac side: find one Creative Commons animal video, download it whole, upload it with its info."""
    if store.keys("inbox/animals/"):  # the server has not taken the last result yet
        return False
    skip = set(job.get("skip", []))
    for e in _cc_search(job["query"], VIDEO_MIN - 4):  # _cc_search keeps duration >= seconds + 4
        if e["id"] in skip or e["duration"] > VIDEO_MAX:
            continue
        workdir = clipper.work_root() / e["id"]
        workdir.mkdir(parents=True, exist_ok=True)
        out = workdir / "source.mp4"
        out.unlink(missing_ok=True)
        r = subprocess.run(["yt-dlp", "-f", f"{clipper.VIDEO_FORMAT}/b[height<=1080]", "--no-playlist",
                            "--merge-output-format", "mp4", "-o", str(out), e["webpage_url"]],
                           capture_output=True, text=True)
        if r.returncode or not out.exists() or _video_seconds(out) < 0.9 * e["duration"]:
            continue  # stub or failed download: try the next result
        info = {"id": e["id"], "title": e.get("title") or "", "channel": e.get("channel") or e.get("uploader") or "",
                "webpage_url": e["webpage_url"], "license": e["license"], "duration": e["duration"]}
        (workdir / "source-audio.info.json").write_text(json.dumps(info, ensure_ascii=False))
        store.put(f"work/{e['id']}/source.mp4", out)
        store.put(f"work/{e['id']}/source-audio.info.json", workdir / "source-audio.info.json")
        store.put_json(f"inbox/animals/{e['id']}.json", {
            "page": job["page"], "video_id": e["id"], "url": e["webpage_url"], "title": info["title"],
            "channel": info["channel"], "license": e["license"]})
        return True
    store.put_json("inbox/animals/none.json", {"none": True, "page": job["page"], "query": job["query"]})
    return False


# --- pick ---

class Moment(BaseModel):
    start: float
    end: float
    title: str
    hook_text: str
    cards: list[writing.Card]
    flags: list[str]
    hook: int = Field(ge=1, le=5)
    standalone: int = Field(ge=1, le=5)
    payoff: int = Field(ge=1, le=5)
    emotion: int = Field(ge=1, le=5)


class Moments(BaseModel):
    moments: list[Moment]


PICK_RULES = """\
You choose clips for @{handle}, an Instagram page of animal videos ({topics}).
The images are contact sheets of one video, "{title}" ({duration:.0f} seconds long): a frame every {every:g} seconds,
left to right then top to bottom, each stamped with its time in seconds. Scene cuts at: {cuts}.

Pick up to {want} moments for short vertical reels with no voiceover and no captions:
- Each is a complete little story that stands alone: a setup, then a payoff (the jump, the fail, the reaction).
- Start just before the action begins and end right after the payoff. Use a scene cut as start or end where one is near.
- Length is {lo} to {hi} seconds, inside 0 to {duration:.0f}. Moments never overlap.
- Skip intros, title cards, subscribe screens, someone talking to camera, and frames covered in text.

For each moment write:
- title: a short working title.
- hook_text: at most 8 words on screen for the first seconds, in English. No emojis, hashtags or dashes.
- cards: 1 or 2 context cards with a fact or context the clip does not show, such as why cats do this. `at` is in
  source seconds inside the moment, title short, body one short sentence. Never invent specifics about these exact
  animals (names, ages, places). No dashes.
- flags: {restricted} Also flag an animal that looks hurt, in distress or mistreated.
- Scores from 1 to 5: hook (first 3 seconds stop the scroll), standalone (needs no context), payoff (a satisfying
  end), emotion (funny, cute, surprising or moving). Be strict: most land at 2 to 4, and 5 is rare.
"""


def contact_sheets(video: Path, duration: float, folder: Path) -> tuple[list[Path], float]:
    """Frames every few seconds, 320 px wide, stamped with their time and tiled 4x4 per png."""
    every = max(EVERY, round(duration / (TILE * TILE * MAX_SHEETS) + 0.5))
    folder.mkdir(parents=True, exist_ok=True)
    for old in folder.glob("sheet-*.png"):
        old.unlink()
    stamp = (f"drawtext=fontfile={clipper.FONTS / 'Inter.ttf'}:text='%{{eif\\:t\\:d}}s':fontsize=26:fontcolor=white:"
             "box=1:boxcolor=black@0.6:boxborderw=6:x=8:y=8")
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(video), "-vf",
                    f"fps=1/{every},scale=320:-2,{stamp},tile={TILE}x{TILE}:padding=4", "-an",
                    str(folder / "sheet-%02d.png")], check=True, capture_output=True)
    return sorted(folder.glob("sheet-*.png")), every


def pick_moments(page, info: dict, duration: float, cuts: list[float], sheets: list[Path], every: float) -> list[Moment]:
    prompt = PICK_RULES.format(handle=page.handle, topics=writing._topics(page), title=info.get("title", ""),
                               duration=duration, every=every, cuts=", ".join(f"{c:.1f}" for c in cuts) or "none found",
                               want=page.clips_per_video, lo=CLIP_MIN, hi=CLIP_MAX, restricted=writing.RESTRICTED)
    return llm.ask(prompt, Moments, images=sheets).moments


def keep(moments: list[Moment], duration: float, want: int) -> list[Moment]:
    kept = []
    for m in sorted(moments, key=lambda m: -clipper.rank_score(m.model_dump())):
        if not (0 <= m.start and m.end <= duration and CLIP_MIN <= m.end - m.start <= CLIP_MAX):
            continue
        if len(m.hook_text.split()) > 8 or not 1 <= len(m.cards) <= 2 or any(not m.start <= c.at <= m.end for c in m.cards):
            continue
        if any(m.start < k.end and k.start < m.end for k in kept):
            continue
        kept.append(m)
    return kept[:want]


# --- cut: pick, render, draft ---

def cut(db, cfg, row) -> None:
    page, vid = cfg.pages[row["page"]], row["video_id"]
    workdir = _pull(vid)
    video = workdir / "source.mp4"
    info = json.loads((workdir / "source-audio.info.json").read_text())
    duration = clipper.duration_of(video)
    sheets, every = contact_sheets(video, duration, workdir / "sheets")
    kept = keep(pick_moments(page, info, duration, clipper.shot_cuts(video, 0, duration), sheets, every),
                duration, page.clips_per_video)
    if not kept:
        _set(db, row, "skipped", "no usable moments")
        return
    (workdir / "meta.json").write_text(json.dumps({"title": info["title"], "url": info["webpage_url"], "path": str(video),
                                                   "duration": duration, "language": "en"}))
    (workdir / "transcript.json").write_text(json.dumps({"language": "en", "source": "none", "segments": []}))
    os.environ["MUSUBI_CLIPS_OFFLINE"] = "1"
    text = f"🎥 {info['title']} by {info['channel']} (CC BY)"
    # text/url for the review UI; credit/page_url is what pages/web.py reads today
    credits = [{"text": text, "url": info["webpage_url"], "credit": text, "page_url": info["webpage_url"]}]
    previous = [c for (c,) in db.execute("select caption from clips where page = ? and caption is not null "
                                         "order by id desc limit 50", (page.handle,))]
    for m in kept:
        moment = {**m.model_dump(), "reason": m.title, "emphasis": []}
        clip_id = db.execute('insert into clips (page, video_id, kind, start, "end", moment, status, created_at) '
                             "values (?, ?, 'clip', ?, ?, ?, 'planned', ?)",
                             (page.handle, vid, m.start, m.end, json.dumps(moment, ensure_ascii=False), _now())).lastrowid
        db.commit()
        try:
            music = None
            if page.music:
                key = random.choice(page.music)
                music = store.get(key, config.HOME / "tmp" / key)
            out = workdir / "out" / f"{clip_id}.mp4"
            clipper.render_one(workdir, {**moment, "cards": [{**c, "hold": 4} for c in moment["cards"]]}, out,
                               theme=page.theme, intro=None, outro=None, music=music)
            key = f"clips/{clip_id}.mp4"
            store.put(key, out)
            caption = writing.write_caption(page, f"{m.title}. {m.hook_text}. " + " ".join(c.body for c in m.cards),
                                            [text], previous)
            previous.append(caption)
            db.execute("update clips set layer = ?, credits = ?, file_key = ?, caption = ?, status = 'draft' where id = ?",
                       (json.dumps({"cards": moment["cards"], "flags": m.flags}, ensure_ascii=False),
                        json.dumps(credits, ensure_ascii=False), key, caption, clip_id))
        except Exception as e:
            db.execute("update clips set status = 'failed', reason = ? where id = ?", (str(e), clip_id))
        db.commit()
    _set(db, row, "cut")


def step(db, cfg) -> None:
    take_inbox(db, cfg)
    write_jobs(db, cfg)
    handles = {p.handle for p in _pages(cfg)}
    row = next((r for r in db.execute("select * from source_videos where status = 'downloaded' order by id").fetchall()
                if r["page"] in handles), None)
    if row:
        try:
            cut(db, cfg, row)
        except Exception as e:
            _set(db, row, "failed", str(e))
            event(db, row["page"], "animals_failed", f"{row['video_id']}: {e}")
