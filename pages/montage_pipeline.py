"""Montage reels (engine/montage.py): beat-cut visual montages from Creative Commons videos (kind "montage") and
rapid fire one-liners from a prepared podcast (kind "rapidfire"). A page's `formats` weights decide the mix."""
import json
import os
import subprocess
from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel

from pages import config, llm, store, writing  # config first: it sets MUSUBI_CLIPS_DIR for the engine
from pages.clips_pipeline import _pull, put_cover
from engine import clipper, montage

SOURCE = "cc_youtube"
SHOTS, SHOT_SECONDS, TEXT_BEATS = (8, 15), (1.0, 3.0), (2, 4)
LINES, LINE_SECONDS, LINES_TOTAL = (4, 6), (2.0, 5.0), (13.0, 27.0)  # lines plus their beat padding make 15 to 30 s
SNAP = 0.35  # a line's start and end must sit this close to a sentence's start and end
RECENT = 30  # clips looked at to balance the format mix
SPAN_PAD, SPAN_MIN, SPAN_JOIN = 2.0, 16.0, 4.0  # spans past MIN_CLIP even after sentence snapping  # the moments that make the Mac fetch each line's section


def _now() -> str:
    return datetime.now(UTC).isoformat()


def next_format(db, page, options) -> str:
    """The kind among options (in order of preference on a tie) furthest below its share of page.formats,
    over the page's recent clips; "clip" when the page sets no weights for these options."""
    weights = {k: page.formats.get(k, 0) for k in options}
    total = sum(page.formats.values())
    if not any(weights.values()):
        return "clip" if "clip" in options else options[0]
    kinds = [k for (k,) in db.execute("select kind from clips where page = ? order by id desc limit ?", (page.handle, RECENT))]
    seen = max(1, len(kinds))
    return max((k for k in options if weights[k]), key=lambda k: weights[k] / total - kinds.count(k) / seen)


def _music(page):
    return store.music_bed(page.montage_music or page.music, config.HOME / "tmp" / "music")


def _draft(db, page, kind, video_id, moment, segments, out_dir, *, mode, about, credit_lines, credits):
    """Render a montage into a draft clip row (or a failed one); its id."""
    clip_id = db.execute('insert into clips (page, video_id, kind, start, "end", moment, status, created_at) '
                         "values (?, ?, ?, ?, ?, ?, 'planned', ?)",
                         (page.handle, video_id, kind, segments[0]["start"], segments[-1]["end"],
                          json.dumps(moment, ensure_ascii=False), _now())).lastrowid
    db.commit()
    return _render(db, page, clip_id, moment, segments, out_dir, mode=mode, about=about, credit_lines=credit_lines,
                   credits=credits)


def _render(db, page, clip_id, moment, segments, out_dir, *, mode, about, credit_lines, credits):
    try:
        out = Path(out_dir) / f"{clip_id}.mp4"
        montage.render_montage(segments, out, music=_music(page), theme=page.theme, hook_style=page.hook_style,
                               brand_tag=page.brand_tag, headline=moment["headline"], accent=moment["accent"],
                               text_beats=moment.get("text_beats") or [], mode=mode, seed=clip_id)
        key = f"clips/{clip_id}.mp4"
        store.put(key, out)
        cover = put_cover(clip_id, out, page)
        previous = [c for (c,) in db.execute("select caption from clips where page = ? and caption is not null "
                                             "order by id desc limit 50", (page.handle,))]
        caption = writing.write_caption(page, about, credit_lines, previous)
        db.execute("update clips set layer = ?, credits = ?, file_key = ?, cover_key = ?, caption = ?, status = 'draft' "
                   "where id = ?", (json.dumps({"cards": [], "flags": moment.get("flags") or []}),
                                    json.dumps(credits, ensure_ascii=False), key, cover, caption, clip_id))
    except Exception as e:
        db.execute("update clips set status = 'failed', reason = ? where id = ?", (str(e), clip_id))
    db.commit()
    return clip_id


# --- visual montage ---

class Shot(BaseModel):
    video: str
    start: float
    end: float


class VisualPick(BaseModel):
    shots: list[Shot]
    headline: str
    accent: list[str]
    text_beats: list[str]
    flags: list[str]


VISUAL_RULES = """\
You cut a fast, beat-synced montage reel for @{handle}, an Instagram page of short visual reels ({topics}).
The images are contact sheets of {count} video(s): a frame every few seconds, left to right then top to bottom, each
stamped with its time in seconds. Each sheet's file name holds its video's id. The videos:
{videos}

Pick {lo} to {hi} shots in the order they should play:
- Each shot is {slo:g} to {shi:g} seconds of the most striking motion: sparks, a fast arm swing, a cut landing, a reveal,
  a machine at full speed. Skip still, slow or repetitive frames, and never use the same moment twice.
- `video` is the video id, `start` and `end` are seconds inside that video. Open on the strongest shot.
- Skip intros, title cards, subscribe screens, someone talking to camera, and frames covered in text.
- Skip any shot showing a watermark, a channel or app logo, a TikTok or Instagram handle, or another creator's name
  anywhere in the frame. Such footage belongs to someone else.

Also write:
- headline: a factual news headline of 6 to 14 words in English, shown big on the opening frames and the cover, like a
  tech news page: specific, often with a number or a twist. Say only what the footage actually shows: no invented
  names, numbers or places, no exaggeration. No emojis, hashtags or dashes.
- accent: 1 to 3 single words copied from the headline to colour, the ones it turns on.
- text_beats: 2 to 4 short punchy lines of at most 5 words each that pop on the beat later in the reel ("ZERO HUMAN
  HANDS", "CUTS STEEL LIKE PAPER"). Each may land over any shot, so it must hold for the whole montage; no
  invented numbers. No emojis or dashes.
- flags: {restricted}
"""


def visual_problems(pick: VisualPick, durations: dict) -> list[str]:
    problems = []
    if not SHOTS[0] <= len(pick.shots) <= SHOTS[1]:
        problems.append(f"pick {SHOTS[0]} to {SHOTS[1]} shots, not {len(pick.shots)}")
    for i, s in enumerate(pick.shots, 1):
        if s.video not in durations:
            problems.append(f"shot {i}: unknown video {s.video}")
        elif not (0 <= s.start and s.end <= durations[s.video]):
            problems.append(f"shot {i}: {s.start}-{s.end} is outside the video")
        if not SHOT_SECONDS[0] - 0.05 <= s.end - s.start <= SHOT_SECONDS[1] + 0.05:
            problems.append(f"shot {i}: must last {SHOT_SECONDS[0]:g} to {SHOT_SECONDS[1]:g} seconds")
        if any(o.video == s.video and o.start < s.end and s.start < o.end for o in pick.shots[:i - 1]):
            problems.append(f"shot {i}: repeats footage of an earlier shot")
    problems += headline_problems(pick.headline, pick.accent)
    if not TEXT_BEATS[0] <= len(pick.text_beats) <= TEXT_BEATS[1]:
        problems.append(f"write {TEXT_BEATS[0]} to {TEXT_BEATS[1]} text beats")
    problems += [f"text beat {t!r}: at most {montage.TEXT_BEAT_WORDS} words" for t in pick.text_beats
                 if not 1 <= len(t.split()) <= montage.TEXT_BEAT_WORDS]
    return problems


def headline_problems(headline: str, accent: list[str]) -> list[str]:
    lo, hi = writing.HOOK_WORDS["headline"]
    problems = [] if lo <= len(headline.split()) <= hi else [f"the headline needs {lo} to {hi} words"]
    words = {clipper._key(w) for w in headline.split()}
    picked = [w for a in accent for w in a.split()]  # "robot arm" colours both words; the engine colours up to 4
    if not 1 <= len(accent) <= 3 or len(picked) > 4 or any(clipper._key(w) not in words for w in picked):
        problems.append(f"accent {accent}: 1 to 3 single words copied exactly from the headline {headline!r}")
    return problems


def _ask(prompt, schema, check, images=None):
    """Ask, and once more with what was wrong; ValueError when the second answer is still wrong."""
    for attempt in range(2):
        pick = llm.ask(prompt, schema, images=images)
        problems = check(pick)
        if not problems:
            return pick
        prompt += "\n\nYour last answer had these problems, fix them:\n" + "\n".join(f"- {p}" for p in problems)
    raise ValueError("; ".join(problems))


def make_visual(db, cfg, page, video_ids: list[str]) -> int:
    """A visual montage from 1 to 3 downloaded Creative Commons videos, as a draft; the clip id."""
    from pages.animals_pipeline import contact_sheets

    videos = {}
    for vid in video_ids[:3]:
        workdir = _pull(vid)
        info = json.loads((workdir / "source-audio.info.json").read_text())
        duration = clipper.duration_of(workdir / "source.mp4")
        sheets, every = contact_sheets(workdir / "source.mp4", duration, workdir / "sheets")
        named = []
        for s in sheets:  # the id in each sheet's name tells Claude which video it shows
            named.append(s.rename(s.with_name(f"{vid}-{s.name}")))
        videos[vid] = {"path": workdir / "source.mp4", "info": info, "duration": duration, "sheets": named, "every": every}
    listing = "\n".join(f"- {vid}: \"{v['info'].get('title', '')}\", {v['duration']:.0f} seconds, a frame every {v['every']:g} s"
                        for vid, v in videos.items())
    prompt = VISUAL_RULES.format(handle=page.handle, topics=writing._topics(page), count=len(videos), videos=listing,
                                 lo=SHOTS[0], hi=SHOTS[1], slo=SHOT_SECONDS[0], shi=SHOT_SECONDS[1],
                                 restricted=writing.RESTRICTED)
    pick = _ask(prompt, VisualPick, lambda p: visual_problems(p, {k: v["duration"] for k, v in videos.items()}),
                images=[s for v in videos.values() for s in v["sheets"]])
    segments = [{"video": videos[s.video]["path"], "start": s.start, "end": s.end} for s in pick.shots]
    credits = []
    for vid, v in videos.items():
        if any(s.video == vid for s in pick.shots):
            text = f"🎥 {v['info'].get('channel', '')}: {v['info']['webpage_url']} (CC BY)"
            credits.append({"text": text, "url": v["info"]["webpage_url"], "credit": text, "page_url": v["info"]["webpage_url"]})
    moment = {"title": pick.headline, "hook_text": pick.headline, "headline": pick.headline, "accent": pick.accent,
              "text_beats": pick.text_beats, "flags": pick.flags, "shots": [s.model_dump() for s in pick.shots]}
    os.environ["MUSUBI_CLIPS_OFFLINE"] = "1"
    first = pick.shots[0].video
    return _draft(db, page, "montage", first, moment, segments, config.HOME / "work" / first / "out", mode="visual",
                  about=f"{pick.headline}. " + ". ".join(pick.text_beats),
                  credit_lines=[c["text"] for c in credits], credits=credits)


# --- rapid fire ---

class Line(BaseModel):
    start: float
    end: float
    text: str


class RapidPick(BaseModel):
    lines: list[Line]
    headline: str
    accent: list[str]
    flags: list[str]


RAPID_RULES = """\
You cut a rapid fire reel for @{handle} ({topics}): {lo} to {hi} of the punchiest one-liners from this podcast, played
back to back on the beat of a bassy track, with word captions.
Each sentence below is `[start-end seconds] text`. A line is one sentence, or two or three back to back sentences that
together make one complete thought.

- Each line is {slo:g} to {shi:g} seconds long and complete: it starts on the first word of a sentence and ends on the
  last word of one. Copy `start` from the first sentence and `end` from the last sentence exactly.
- Pick bold claims, numbers, sharp opinions, quotable lines. Each must make sense on its own, with no "he", "that"
  or "as I said" pointing at something outside the line.
- Together, in the order you give them, they must make sense as a sequence on one theme, building to the strongest
  line last. Lines never overlap. All lines together run {tlo:g} to {thi:g} seconds.
- headline: a factual news headline of 6 to 14 words in English for the opening frames and the cover: who said what,
  specific, drawn only from what is said (name someone only when the video title makes it clear). No emojis,
  hashtags or dashes.
- accent: 1 to 3 single words copied from the headline to colour.
- flags: {restricted}

Video title: {title}

Sentences:
{sentences}
"""


def _near(t, options):
    best = min(options, key=lambda o: abs(o - t), default=None)
    return best if best is not None and abs(best - t) <= SNAP else None


def line_problems(lines: list[Line], sentences: list[dict]) -> list[str]:
    """Each line a run of whole sentences, 2 to 5 s; 4 to 6 lines that never overlap and run 13 to 27 s together."""
    problems = []
    if not LINES[0] <= len(lines) <= LINES[1]:
        problems.append(f"pick {LINES[0]} to {LINES[1]} lines, not {len(lines)}")
    starts, ends = [s["start"] for s in sentences], [s["end"] for s in sentences]
    for i, line in enumerate(lines, 1):
        if _near(line.start, starts) is None:
            problems.append(f"line {i}: {line.start} is not the start of a sentence")
        if _near(line.end, ends) is None:
            problems.append(f"line {i}: {line.end} is not the end of a sentence")
        if not LINE_SECONDS[0] <= line.end - line.start <= LINE_SECONDS[1]:
            problems.append(f"line {i}: lasts {line.end - line.start:.1f} s, not {LINE_SECONDS[0]:g} to {LINE_SECONDS[1]:g}")
        if any(o.start < line.end and line.start < o.end for o in lines[:i - 1]):
            problems.append(f"line {i}: overlaps an earlier line")
    total = sum(line.end - line.start for line in lines)
    if not LINES_TOTAL[0] <= total <= LINES_TOTAL[1]:
        problems.append(f"the lines run {total:.1f} s together, not {LINES_TOTAL[0]:g} to {LINES_TOTAL[1]:g}")
    return problems


def snapped(lines: list[Line], sentences: list[dict]) -> list[dict]:
    starts, ends = [s["start"] for s in sentences], [s["end"] for s in sentences]
    return [{"start": _near(line.start, starts), "end": _near(line.end, ends), "text": line.text} for line in lines]


def fetch_moments(lines: list[dict], headline: str) -> list[dict]:
    """Spans that cover every line, written as moments.json so the Mac's section fetch downloads them
    (each at least SPAN_MIN s and apart from the others, so the engine's moment checks keep them all)."""
    spans = []
    for a, b in sorted((line["start"] - SPAN_PAD, line["end"] + SPAN_PAD) for line in lines):
        if spans and a - spans[-1][1] < SPAN_JOIN:
            spans[-1][1] = max(spans[-1][1], b)
        else:
            spans.append([a, b])
    out = []
    for a, b in spans:
        grow = max(0.0, SPAN_MIN - (b - a)) / 2
        a, b = max(0.0, a - grow), b + grow
        if out and a - out[-1]["end"] < SPAN_JOIN:
            out[-1]["end"] = round(b, 3)
            continue
        out.append({"start": round(a, 3), "end": round(b, 3), "title": "rapid fire", "hook_text": headline,
                    "reason": "rapid fire lines", "emphasis": [], "hook": 3, "standalone": 3, "payoff": 3, "emotion": 3})
    return out


def pick_rapidfire(page, workdir: Path, title: str) -> dict:
    """Claude's lines for a rapid fire reel, checked and snapped to sentence edges."""
    words = clipper.all_words(json.loads((workdir / "transcript.json").read_text()))
    sentences = [s for s in clipper.spoken_sentences(words) if s["end"] - s["start"] <= LINE_SECONDS[1]]
    listing = "\n".join(f"[{s['start']:.2f}-{s['end']:.2f}] {s['text']}" for s in sentences)
    prompt = RAPID_RULES.format(handle=page.handle, topics=writing._topics(page), lo=LINES[0], hi=LINES[1],
                                slo=LINE_SECONDS[0], shi=LINE_SECONDS[1], tlo=LINES_TOTAL[0], thi=LINES_TOTAL[1],
                                restricted=writing.RESTRICTED, title=title, sentences=listing)
    pick = _ask(prompt, RapidPick, lambda p: line_problems(p.lines, sentences) + headline_problems(p.headline, p.accent))
    return {"title": pick.headline, "hook_text": pick.headline, "headline": pick.headline, "accent": pick.accent,
            "flags": pick.flags, "lines": snapped(pick.lines, sentences)}


def plan_rapidfire(db, page, video_row, workdir: Path) -> int:
    """Pick the lines, write moments.json so the Mac fetches their sections, and plan the clip; its id."""
    meta = json.loads((workdir / "meta.json").read_text())
    moment = pick_rapidfire(page, workdir, video_row["title"] or meta["title"])
    vid = video_row["video_id"]
    (workdir / "moments.json").write_text(json.dumps(fetch_moments(moment["lines"], moment["headline"]), ensure_ascii=False))
    store.put(f"work/{vid}/moments.json", workdir / "moments.json")
    if meta.get("language", "en") != "en":  # English captions for the lines, as pick does for clips
        (workdir / "english.json").write_text(json.dumps(writing.translate(clipper.untranslated(workdir)), ensure_ascii=False))
        store.put(f"work/{vid}/english.json", workdir / "english.json")
    clip_id = db.execute('insert into clips (page, video_id, kind, start, "end", moment, status, created_at) '
                         "values (?, ?, 'rapidfire', ?, ?, ?, 'planned', ?)",
                         (page.handle, vid, moment["lines"][0]["start"], moment["lines"][-1]["end"],
                          json.dumps(moment, ensure_ascii=False), _now())).lastrowid
    db.commit()
    return clip_id


def rapidfire_credit(workdir: Path, title: str, src=None) -> str:
    info = json.loads((workdir / "source-audio.info.json").read_text())
    channel = info.get("channel") or info.get("uploader") or ""
    cc = " (CC BY)" if "Creative Commons" in (info.get("license") or "") else ""
    return f"🎙️ {title}" + (f" by {channel}" if channel else "") + cc + (f" via @{src.instagram}" if src and src.instagram else "")


def make_rapidfire(db, page, clip_row, workdir: Path, credit: str) -> int:
    """Render a planned rapid fire clip from its fetched sections into a draft (or a failed row)."""
    moment = json.loads(clip_row["moment"])
    try:
        meta = json.loads((workdir / "meta.json").read_text())
        words = clipper.english_words(workdir, meta.get("language", "en")) or clipper.all_words(
            json.loads((workdir / "transcript.json").read_text()))
        stream = clipper.find_stream(workdir, meta)
        segments = []
        for line in moment["lines"]:
            video, offset = clipper.video_section(workdir, meta, {"start": line["start"] - 0.5, "end": line["end"] + 0.8,
                                                                  "cold_open": None}, stream)
            segments.append({"video": video, "start": line["start"] - offset, "end": line["end"] - offset,
                             "words": [{**w, "start": w["start"] - offset, "end": w["end"] - offset} for w in words
                                       if line["start"] - 0.05 <= w["start"] < line["end"]]})
    except (Exception, SystemExit) as e:  # a missing section fails this reel, not the video's other clips
        db.execute("update clips set status = 'failed', reason = ? where id = ?", (str(e), clip_row["id"]))
        db.commit()
        return clip_row["id"]
    return _render(db, page, clip_row["id"], moment, segments, workdir / "out", mode="speech",
                   about=f"{moment['headline']}. " + " ".join(line["text"] for line in moment["lines"]),
                   credit_lines=[credit], credits=[credit])


# --- on demand (`pages montage`) ---

AV_FORMAT = "bv*[height<=1080][vcodec^=avc1]+ba[ext=m4a]/bv*[height<=1080]+ba/b[height<=1080]"


def _download_cc(vid: str) -> None:
    """Mac side: download a whole Creative Commons video into the store, as the animals fetcher does."""
    url = f"https://www.youtube.com/watch?v={vid}"
    info = json.loads(subprocess.run(["yt-dlp", "-J", "--no-playlist", url], capture_output=True, text=True, check=True).stdout)
    if "Creative Commons" not in (info.get("license") or ""):
        raise ValueError(f"{vid} is not Creative Commons")
    workdir = clipper.work_root() / vid
    workdir.mkdir(parents=True, exist_ok=True)
    out = workdir / "source.mp4"
    if not out.exists():
        subprocess.run(["yt-dlp", "-f", AV_FORMAT, "--no-playlist", "--merge-output-format", "mp4", "-o", str(out), url],
                       capture_output=True, check=True)
    keep = {"id": vid, "title": info.get("title") or "", "channel": info.get("channel") or info.get("uploader") or "",
            "webpage_url": info["webpage_url"], "license": info["license"], "duration": info.get("duration")}
    (workdir / "source-audio.info.json").write_text(json.dumps(keep, ensure_ascii=False))
    store.put(f"work/{vid}/source.mp4", out)
    store.put(f"work/{vid}/source-audio.info.json", workdir / "source-audio.info.json")


def on_demand(db, cfg, handle: str, kind: str, videos: list[str] | None) -> int:
    """`pages montage`: make one montage now, as a draft for review; the clip id."""
    page = cfg.pages[handle]
    if kind == "visual":
        if not videos:
            videos = [v for (v,) in db.execute("select video_id from source_videos where page = ? and source_id = ? "
                                               "order by id desc", (handle, SOURCE)) if store.exists(f"work/{v}/source.mp4")][:3]
        if not videos:
            raise ValueError("no downloaded Creative Commons video for this page: pass --videos")
        for vid in videos:
            if not store.exists(f"work/{vid}/source.mp4"):
                _download_cc(vid)
            info = store.get_json(f"work/{vid}/source-audio.info.json")
            db.execute("insert or ignore into source_videos (source_id, page, video_id, url, title, status, note, created_at) "
                       "values (?, ?, ?, ?, ?, 'cut', ?, ?)", (SOURCE, handle, vid, info["webpage_url"], info["title"],
                                                              f"{info['license']} · {info['channel']} · {info['webpage_url']}", _now()))
        db.commit()
        return make_visual(db, cfg, page, videos)
    if not videos:
        row = db.execute("select video_id from source_videos where page = ? and (source_id is null or source_id != ?) "
                         "and status in ('prepared', 'picked', 'fetched', 'cut') order by id desc", (handle, SOURCE)).fetchone()
        if not row:
            raise ValueError("no prepared podcast for this page: pass --videos")
        videos = [row[0]]
    row = db.execute("select * from source_videos where video_id = ?", (videos[0],)).fetchone()
    workdir = _pull(videos[0])
    meta = json.loads((workdir / "meta.json").read_text())
    title = (row["title"] if row else None) or meta["title"]
    clip_id = plan_rapidfire(db, page, row or {"video_id": videos[0], "title": title}, workdir)
    src = cfg.sources.get(row["source_id"] or "") if row else None
    clip = db.execute("select * from clips where id = ?", (clip_id,)).fetchone()
    return make_rapidfire(db, page, clip, workdir, rapidfire_credit(workdir, title, src))
