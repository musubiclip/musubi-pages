"""Clip pipeline (podcastbawaal): jobs for the Mac, intake, pasted links, moment picking, making clips."""
import json
import os
import re
from datetime import UTC, datetime
from pathlib import Path

from pages import config, llm, store, writing  # config first: it sets MUSUBI_CLIPS_DIR for the engine
from pages.db import QUEUE_LOW, queue_size
from engine import clipper

MUSIC_TAGS = ("[Music]", "[संगीत]", "♪")
CLIP_SECONDS = (15, 30)  # as played: after silence trimming, cold open included
RAW_MAX = 36  # a picked span may run longer than 30 s by the pauses trimmed out of it


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _set(db, row, status, note=None) -> None:
    db.execute("update source_videos set status = ?, note = coalesce(?, note) where id = ?", (status, note, row["id"]))
    db.commit()


def _channels(cfg, page=None):
    return [s for s in cfg.sources.values() if s.kind == "youtube_channel" and (page is None or s.page == page)
            and cfg.pages[s.page].active]


def write_jobs(db, cfg) -> None:
    videos = lambda status: [v for v in db.execute("select * from source_videos where status = ? order by id",
                                                   (status,)).fetchall() if cfg.pages[v["page"]].active]
    store.put_json("jobs/fetch.json", {
        "watch": [{"source": s.id, "url": s.url} for s in _channels(cfg) if queue_size(db, s.page) < QUEUE_LOW],
        "prepare": [{"video_id": v["video_id"], "url": v["url"]} for v in videos("new")
                    if queue_size(db, v["page"]) < QUEUE_LOW],
        "sections": [{"video_id": v["video_id"], "url": v["url"], "count": _section_count(db, cfg, v)}
                     for v in videos("picked")],
        "cc_search": [],
    })


def _section_count(db, cfg, video) -> int:
    """Moments the Mac fetches sections for: a rapid fire reel writes one per group of its lines."""
    from pages.montage_pipeline import LINES
    rapid = db.execute("select 1 from clips where video_id = ? and kind = 'rapidfire'", (video["video_id"],)).fetchone()
    return LINES[1] if rapid else cfg.pages[video["page"]].clips_per_video


def take_inbox(db, cfg) -> None:
    for src in _channels(cfg):
        since = src.since.isoformat() if src.since else ""
        for v in store.get_json(f"inbox/{src.id}.json", []):
            if v.get("published") and v["published"] < since:
                continue
            db.execute("insert or ignore into source_videos (source_id, page, video_id, url, title, published, status, "
                       "created_at) values (?, ?, ?, ?, ?, ?, 'new', ?)",
                       (src.id, src.page, v["video_id"], v["url"], v.get("title"), v.get("published"), _now()))
    db.commit()


def video_id(url: str) -> str | None:
    m = re.match(r"https?://(?:www\.|m\.)?(?:youtu\.be/|youtube\.com/(?:watch\?(?:.*&)?v=|shorts/))([\w-]+)", url.strip())
    return m[1] if m else None


def add_link(db, cfg, url: str, page: str, note: str) -> int:
    if page not in cfg.pages:
        raise ValueError(f"unknown page {page}")
    if cfg.pages[page].pipeline != "clips":
        raise ValueError("links only go to clip pages")
    vid = video_id(url)
    if not vid:
        raise ValueError(f"not a YouTube video link: {url}")
    used = db.execute("select page from source_videos where video_id = ?", (vid,)).fetchone()
    if used:
        raise ValueError(f"already used by {used['page']}")
    cur = db.execute("insert into source_videos (source_id, page, video_id, url, status, note, created_at) "
                     "values (null, ?, ?, ?, 'new', ?, ?)",
                     (page, vid, f"https://www.youtube.com/watch?v={vid}", note or None, _now()))
    db.commit()
    return cur.lastrowid


def belongs(info: dict, source_url: str) -> bool:
    norm = lambda u: (u or "").strip().rstrip("/").lower()
    return bool(source_url) and norm(source_url) in {norm(info.get("channel_url")), norm(info.get("uploader_url"))}


def advance(db, cfg) -> None:
    for row in db.execute("select * from source_videos where status = 'new'").fetchall():
        base = f"work/{row['video_id']}/"
        if store.exists(base + "error.txt"):
            _set(db, row, "skipped", _text(base + "error.txt"))
        elif store.exists(base + "transcript.json"):
            if row["source_id"]:
                _set(db, row, "prepared")
                continue
            info = store.get_json(base + "source-audio.info.json", {})
            src = next((s for s in _channels(cfg, row["page"]) if belongs(info, s.url)), None)
            if src:
                db.execute("update source_videos set source_id = ? where id = ?", (src.id, row["id"]))
                _set(db, row, "prepared")
            elif row["note"]:
                _set(db, row, "prepared")  # a one-off permission, recorded in the note
            else:
                _set(db, row, "skipped", "not an allowed source")
    for row in db.execute("select * from source_videos where status = 'picked'").fetchall():
        if store.exists(f"work/{row['video_id']}/sections.done"):
            _set(db, row, "fetched")


def put_cover(clip_id: int, out: Path, page) -> str | None:
    """Store the cover frame render_one wrote beside the video and the branded cover made from it;
    the branded cover's key, or None when there is no frame."""
    from pages.covers import make_cover
    frame = out.with_suffix(".jpg")
    if not frame.exists():
        return None
    store.put(f"clips/{clip_id}.jpg", frame)
    key = f"clips/{clip_id}-cover.jpg"
    store.put(key, make_cover(frame, page, out.with_name(f"{out.stem}-cover.jpg")))
    return key


def _text(key: str) -> str:
    return store.get(key, config.HOME / "tmp" / key).read_text().strip()


def _pull(vid: str) -> Path:
    """Copy work/<vid>/ from the store into the local work folder."""
    workdir = config.HOME / "work" / vid
    for key in store.keys(f"work/{vid}/"):
        store.get(key, workdir / key[len(f"work/{vid}/"):])
    return workdir


# --- pick ---

def music_spans(json3_text: str) -> list[tuple[float, float]]:
    spans = []
    for e in json.loads(json3_text).get("events", []):
        text = "".join(s.get("utf8", "") for s in e.get("segs") or [])
        if any(tag in text for tag in MUSIC_TAGS):
            start = e["tStartMs"] / 1000
            spans.append((start, start + e.get("dDurationMs", 0) / 1000))
    return spans


def strongest_hook(m: dict, words: tuple[int, int] = (1, 8)) -> dict | None:
    """Keep the best scored hook candidate (words long, no dashes); None when no usable hook is left."""
    ok = lambda t: words[0] <= len(t.split()) <= words[1] and not re.search(r"[–—]| - ", t)
    best = max((c for c in m.get("hook_candidates") or [] if ok(c["text"])), key=lambda c: c["score"], default=None)
    if best and best["text"].strip() != m["hook_text"].strip():
        # the parts and accent were written for another hook
        m = {**m, "hook_text": best["text"].strip(), "hook_parts": None, "hook_accent": []}
    return m if ok(m["hook_text"]) else None


def cold_open(m: dict) -> tuple[float | None, float | None]:
    """The cold open when it is a 2 to 5 s line inside the moment (past its first second), else none."""
    cs, ce = m.get("cold_open_start"), m.get("cold_open_end")
    if cs is not None and ce is not None and m["start"] + 1 < cs < ce <= m["end"] and 2 <= ce - cs <= 5:
        return cs, ce
    return None, None


def pick(db, cfg, video_row) -> None:
    page, vid = cfg.pages[video_row["page"]], video_row["video_id"]
    workdir = _pull(vid)
    meta = json.loads((workdir / "meta.json").read_text())
    from pages import montage_pipeline
    if montage_pipeline.next_format(db, page, ("clip", "rapidfire")) == "rapidfire":
        try:
            montage_pipeline.plan_rapidfire(db, page, video_row, workdir)
            _set(db, video_row, "picked")
            return
        except (ValueError, llm.LLMError):
            pass  # no good set of lines: clip the video instead
    transcript = json.loads((workdir / "transcript.json").read_text())
    music = [s for f in workdir.glob("captions.*.json3") for s in music_spans(f.read_text())]
    found = writing.pick_moments((workdir / "transcript.txt").read_text(), video_row["title"] or meta["title"],
                                 page.clips_per_video, topics=writing._topics(page), hook_style=page.hook_style)
    words = clipper.all_words(transcript)
    good = []
    for m in (m.model_dump() for m in found):
        if clipper.moment_problems([m]) or not CLIP_SECONDS[0] <= m["end"] - m["start"] <= RAW_MAX:
            continue
        if any(a < m["end"] and m["start"] < b for a, b in music):
            continue
        m = strongest_hook(m, writing.HOOK_WORDS[page.hook_style])
        if m is None:
            continue
        m["cold_open_start"], m["cold_open_end"] = cold_open(m)
        m["skip"] = clipper.merge_spans((m.get("skip") or []) + clipper.silence_skips(words, m["start"], m["end"]))
        m["max_seconds"] = CLIP_SECONDS[1]
        good.append(m)
    kept = [c for c in clipper.tidy_clips(good, words, len(good))
            if clipper.played_seconds(c) >= CLIP_SECONDS[0]][:page.clips_per_video]
    if not kept:
        _set(db, video_row, "skipped", "no usable moments")
        return
    (workdir / "moments.json").write_text(json.dumps(kept, ensure_ascii=False))
    store.put(f"work/{vid}/moments.json", workdir / "moments.json")
    if meta.get("language", "en") != "en":
        (workdir / "english.json").write_text(json.dumps(writing.translate(clipper.untranslated(workdir)),
                                                         ensure_ascii=False))
        store.put(f"work/{vid}/english.json", workdir / "english.json")
    for m in kept:
        db.execute('insert into clips (page, video_id, kind, start, "end", moment, status, created_at) '
                   "values (?, ?, 'clip', ?, ?, ?, 'planned', ?)",
                   (page.handle, vid, m["start"], m["end"], json.dumps(m, ensure_ascii=False), _now()))
    _set(db, video_row, "picked")


# --- make clips ---

def make_clips(db, cfg, video_row) -> None:
    page, vid = cfg.pages[video_row["page"]], video_row["video_id"]
    src = cfg.sources.get(video_row["source_id"] or "")
    workdir = _pull(vid)
    os.environ["MUSUBI_CLIPS_OFFLINE"] = "1"
    meta = json.loads((workdir / "meta.json").read_text())
    words = clipper.all_words(json.loads((workdir / "transcript.json").read_text()))
    credit = f"🎙️ {video_row['title'] or meta['title']}" + (f" via @{src.instagram}" if src and src.instagram else "")
    previous = [r[0] for r in db.execute("select caption from clips where page = ? and caption is not null "
                                         "order by id desc limit 50", (page.handle,))]
    for clip in db.execute("select * from clips where video_id = ? and status = 'planned'", (vid,)).fetchall():
        if clip["kind"] == "rapidfire":
            from pages import montage_pipeline
            montage_pipeline.make_rapidfire(db, page, clip, workdir, montage_pipeline.rapidfire_credit(
                workdir, video_row["title"] or meta["title"], src))
            continue
        try:
            m = json.loads(clip["moment"])
            if clipper.speaker_share(workdir, m) < clipper.MIN_SPEAKER:
                raise ValueError("no speaker on screen")
            text = " ".join(w["word"] for w in words if m["start"] <= w["start"] <= m["end"])
            layer = writing.write_layer(page, writing.Moment(**m), text)
            music = store.music_bed(page.music, config.HOME / "tmp" / "music")
            out = workdir / "out" / f"{clip['id']}.mp4"
            clipper.MUSIC["volume"] = page.music_volume  # per page bed level
            clipper.render_one(workdir, {**m, "cards": [{**c.model_dump(), "hold": 4} for c in layer.cards]}, out,
                               theme=page.theme, intro=None, outro=None, music=music, sfx=page.sfx,
                               hook_style=page.hook_style, brand_tag=page.brand_tag)
            key = f"clips/{clip['id']}.mp4"
            store.put(key, out)
            cover = put_cover(clip["id"], out, page)
            caption = writing.write_caption(page, f"{m['title']}. {m['reason']}", [credit], previous)
            previous.append(caption)
            db.execute("update clips set layer = ?, credits = ?, file_key = ?, cover_key = ?, caption = ?, status = 'draft' "
                       "where id = ?", (layer.model_dump_json(), json.dumps([credit], ensure_ascii=False), key, cover,
                                        caption, clip["id"]))
        except Exception as e:
            db.execute("update clips set status = 'failed', reason = ? where id = ?", (str(e), clip["id"]))
        db.commit()
    _set(db, video_row, "cut")


def step(db, cfg) -> None:
    write_jobs(db, cfg)
    take_inbox(db, cfg)
    advance(db, cfg)
    for status, work in (("prepared", pick), ("fetched", make_clips)):
        rows = db.execute("select * from source_videos where status = ? order by id", (status,)).fetchall()
        # a full queue picks nothing new: a first watch would otherwise pick every upload of every source
        row = next((r for r in rows if cfg.pages[r["page"]].active
                    and (work is not pick or queue_size(db, r["page"]) < QUEUE_LOW)), None)
        if row:
            try:
                work(db, cfg, row)
            except Exception as e:
                _set(db, row, "failed", str(e))
