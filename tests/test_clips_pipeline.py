import json
import os

import pytest

from engine import clipper
from helpers import add_clip, put_prepared
from pages import clips_pipeline, config, store, voice, writing

POD_INFO = {"channel_url": "https://www.youtube.com/channel/UCpod", "uploader_url": "https://www.youtube.com/@Pod"}
OTHER_INFO = {"channel_url": "https://www.youtube.com/channel/UCother", "uploader_url": "https://www.youtube.com/@other"}


@pytest.fixture(autouse=True)
def home(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "HOME", tmp_path / "home")
    monkeypatch.delenv("MUSUBI_CLIPS_OFFLINE", raising=False)


def long_transcript(language="en"):
    # a word a second for 10 minutes, a sentence every 10 words
    words = [{"word": f"w{i}" + ("." if i % 10 == 9 else ""), "start": float(i), "end": i + 0.8} for i in range(600)]
    segs = [{"start": words[i]["start"], "end": words[i + 9]["end"], "text": " ".join(w["word"] for w in words[i:i + 10]),
             "words": words[i:i + 10]} for i in range(0, 600, 10)]
    return {"language": language, "source": "youtube", "segments": segs}


def add_video(d, vid, status, source_id="pod", note=None):
    d.execute("insert into source_videos (source_id, page, video_id, url, title, status, note) values (?,?,?,?,?,?,?)",
              (source_id, "podcastbawaal", vid, f"https://www.youtube.com/watch?v={vid}", f"Video {vid}", status, note))
    d.commit()
    return d.execute("select * from source_videos where video_id=?", (vid,)).fetchone()


def status(d, vid):
    return d.execute("select status, note from source_videos where video_id=?", (vid,)).fetchone()


def M(start, end, **kw):
    return writing.Moment.model_construct(**{
        "start": start, "end": end, "title": "Burnout", "hook_text": "Founders burn out", "hook_parts": None,
        "reason": "Honest story", "emphasis": ["burn"], "focus_x": None, "speaker_name": None, "speaker_role": None,
        "hook": 4, "standalone": 4, "payoff": 3, "emotion": 3, **kw})


@pytest.fixture
def prepared_video(d, local_store):
    put_prepared(local_store, "vid1", POD_INFO, transcript=long_transcript())
    store.put_json("work/vid1/captions.en-orig.json3",
                   {"events": [{"tStartMs": 20000, "dDurationMs": 10000, "segs": [{"utf8": "[Music]"}]}]})
    return add_video(d, "vid1", "prepared")


@pytest.fixture
def prepared_hindi_video(d, local_store):
    put_prepared(local_store, "vid2", POD_INFO, language="hi", transcript=long_transcript("hi"))
    return add_video(d, "vid2", "prepared")


@pytest.fixture
def fetched_video(d, local_store):
    put_prepared(local_store, "vid3", POD_INFO, transcript=long_transcript())
    store.put_json("work/vid3/sections.done", True)
    row = add_video(d, "vid3", "fetched")
    moment = {**M(100, 150).model_dump(), "cold_open": None, "skip": [], "score": 14}
    add_clip(d, "podcastbawaal", "planned", video_id="vid3", start=100, end=150, moment=json.dumps(moment),
             caption=None, file_key=None)
    add_clip(d, "podcastbawaal", "draft", caption="old caption")
    return row


# --- jobs, inbox, links, advance ---

def test_jobs_watch_only_while_the_queue_is_low(d, cfg_with_podcast, local_store):
    clips_pipeline.write_jobs(d, cfg_with_podcast)
    assert store.get_json("jobs/fetch.json")["watch"] == [{"source": "pod", "url": "https://www.youtube.com/@pod"}]
    for _ in range(7):
        add_clip(d, "podcastbawaal", "draft")
    clips_pipeline.write_jobs(d, cfg_with_podcast)
    assert store.get_json("jobs/fetch.json")["watch"] == []


def test_jobs_list_new_videos_to_prepare_and_picked_to_fetch(d, cfg_with_podcast, local_store):
    add_video(d, "n1", "new")
    add_video(d, "p1", "picked")
    add_video(d, "c1", "cut")
    clips_pipeline.write_jobs(d, cfg_with_podcast)
    jobs = store.get_json("jobs/fetch.json")
    assert jobs["prepare"] == [{"video_id": "n1", "url": "https://www.youtube.com/watch?v=n1"}]
    assert jobs["sections"] == [{"video_id": "p1", "url": "https://www.youtube.com/watch?v=p1", "count": 3}]
    assert jobs["cc_search"] == []


def test_inbox_adds_only_unseen_videos_after_since(d, cfg_with_podcast, local_store):
    add_video(d, "seen", "cut")
    store.put_json("inbox/pod.json", [
        {"video_id": "seen", "url": "u", "title": "Old", "published": "2026-10-05"},
        {"video_id": "old", "url": "u", "title": "Old", "published": "2026-09-30"},
        {"video_id": "fresh", "url": "u", "title": "Fresh", "published": "2026-10-01"},
        {"video_id": "undated", "url": "u", "title": "Undated", "published": None}])
    clips_pipeline.take_inbox(d, cfg_with_podcast)
    clips_pipeline.take_inbox(d, cfg_with_podcast)
    rows = d.execute("select video_id, status, source_id, page from source_videos order by id").fetchall()
    assert [tuple(r) for r in rows] == [("seen", "cut", "pod", "podcastbawaal"),
                                        ("fresh", "new", "pod", "podcastbawaal"),
                                        ("undated", "new", "pod", "podcastbawaal")]


def test_add_link_parses_the_url_forms(d, cfg_with_podcast, local_store):
    for url, vid in [("https://youtu.be/aaa?si=x", "aaa"), ("https://www.youtube.com/watch?v=bbb&t=4", "bbb"),
                     ("https://youtube.com/shorts/ccc", "ccc")]:
        clips_pipeline.add_link(d, cfg_with_podcast, url, "podcastbawaal", "")
        assert status(d, vid)["status"] == "new"
    row = d.execute("select source_id, url from source_videos where video_id='aaa'").fetchone()
    assert row["source_id"] is None and row["url"] == "https://www.youtube.com/watch?v=aaa"
    with pytest.raises(ValueError):
        clips_pipeline.add_link(d, cfg_with_podcast, "https://vimeo.com/1", "podcastbawaal", "")
    with pytest.raises(ValueError):
        clips_pipeline.add_link(d, cfg_with_podcast, "https://youtu.be/ddd", "nopage", "")


def test_link_from_unlisted_channel_is_skipped_without_a_note(d, cfg_with_podcast, local_store):
    vid = clips_pipeline.add_link(d, cfg_with_podcast, "https://www.youtube.com/watch?v=abc", "podcastbawaal", "")
    put_prepared(local_store, "abc", info=OTHER_INFO)
    clips_pipeline.advance(d, cfg_with_podcast)
    row = d.execute("select status, note from source_videos where id=?", (vid,)).fetchone()
    assert row["status"] == "skipped" and "not an allowed source" in row["note"]

    vid = clips_pipeline.add_link(d, cfg_with_podcast, "https://youtu.be/xyz", "podcastbawaal", "one off: host emailed 25 Oct")
    put_prepared(local_store, "xyz", info=OTHER_INFO)
    clips_pipeline.advance(d, cfg_with_podcast)
    assert d.execute("select status from source_videos where id=?", (vid,)).fetchone()[0] == "prepared"


def test_link_from_an_allowed_channel_gets_its_source(d, cfg_with_podcast, local_store):
    clips_pipeline.add_link(d, cfg_with_podcast, "https://youtu.be/abc", "podcastbawaal", "")
    put_prepared(local_store, "abc", info=POD_INFO)
    clips_pipeline.advance(d, cfg_with_podcast)
    row = d.execute("select status, source_id from source_videos where video_id='abc'").fetchone()
    assert tuple(row) == ("prepared", "pod")


def test_advance_skips_errors_and_marks_fetched(d, cfg_with_podcast, local_store):
    add_video(d, "e1", "new")
    store.put_json("work/e1/error.txt", "x")
    (local_store / "work/e1/error.txt").write_text("no captions")
    add_video(d, "w1", "new")
    add_video(d, "p1", "picked")
    store.put_json("work/p1/sections.done", True)
    add_video(d, "p2", "picked")
    clips_pipeline.advance(d, cfg_with_podcast)
    assert tuple(status(d, "e1")) == ("skipped", "no captions")
    assert status(d, "w1")["status"] == "new"
    assert status(d, "p1")["status"] == "fetched" and status(d, "p2")["status"] == "picked"


def test_a_video_belongs_to_one_page_only(d, cfg_with_podcast, local_store):
    clips_pipeline.add_link(d, cfg_with_podcast, "https://youtu.be/abc", "podcastbawaal", "")
    with pytest.raises(ValueError, match="already used by podcastbawaal"):
        clips_pipeline.add_link(d, cfg_with_podcast, "https://www.youtube.com/watch?v=abc", "podcastbawaal", "note")


def test_belongs_matches_handle_or_channel_url():
    assert clips_pipeline.belongs({"uploader_url": "https://www.youtube.com/@Pod"}, "https://www.youtube.com/@pod/")
    assert clips_pipeline.belongs({"channel_url": "https://www.youtube.com/channel/UCpod"},
                                  "https://www.youtube.com/channel/UCpod")
    assert not clips_pipeline.belongs(OTHER_INFO, "https://www.youtube.com/@pod")


# --- pick ---

def test_music_spans_reads_caption_tags():
    j = json.dumps({"events": [{"tStartMs": 1000, "dDurationMs": 4000, "segs": [{"utf8": "[Music]"}]},
                               {"tStartMs": 6000, "dDurationMs": 2000, "segs": [{"utf8": "hello"}]},
                               {"tStartMs": 9000}]})
    assert clips_pipeline.music_spans(j) == [(1.0, 5.0)]


def test_pick_drops_music_short_and_broken_moments(d, cfg_with_podcast, prepared_video, monkeypatch):
    asked = {}

    def fake_pick(transcript, title, want):
        asked.update(transcript=transcript, title=title, want=want)
        return [M(100, 150), M(10, 40), M(300, 310), M(400, 470, hook=None)]
    monkeypatch.setattr(writing, "pick_moments", fake_pick)
    clips_pipeline.pick(d, cfg_with_podcast, prepared_video)
    assert asked["want"] == 3 and asked["title"] == "Video vid1" and "w100" in asked["transcript"]
    clips = d.execute("select * from clips where video_id='vid1'").fetchall()
    assert len(clips) == 1 and clips[0]["status"] == "planned" and clips[0]["kind"] == "clip"
    assert 99 <= clips[0]["start"] <= 100 and json.loads(clips[0]["moment"])["title"] == "Burnout"
    assert [m["start"] for m in store.get_json("work/vid1/moments.json")] == [clips[0]["start"]]
    assert not store.exists("work/vid1/english.json")
    assert status(d, "vid1")["status"] == "picked"


def test_pick_with_nothing_usable_skips_the_video(d, cfg_with_podcast, prepared_video, monkeypatch):
    monkeypatch.setattr(writing, "pick_moments", lambda *a: [M(10, 40)])
    clips_pipeline.pick(d, cfg_with_podcast, prepared_video)
    assert tuple(status(d, "vid1")) == ("skipped", "no usable moments")
    assert d.execute("select count(*) from clips").fetchone()[0] == 0


def test_hindi_video_gets_english_lines(d, cfg_with_podcast, prepared_hindi_video, monkeypatch):
    monkeypatch.setattr(writing, "pick_moments", lambda *a: [M(100, 150)])
    seen = []

    def fake_translate(sentences):
        seen.extend(sentences)
        return [{"start": 100.0, "end": 150.0, "text": "Hello."}]
    monkeypatch.setattr(writing, "translate", fake_translate)
    clips_pipeline.pick(d, cfg_with_podcast, prepared_hindi_video)
    assert seen and seen[0].startswith("[")
    assert store.get_json("work/vid2/english.json") == [{"start": 100.0, "end": 150.0, "text": "Hello."}]


# --- make_clips ---

def fake_layer(page, moment, text):
    return writing.Layer(intro="Here is why founders burn out", takeaway="Rest is part of the work",
                         cards=[writing.Card(at=120, title="Fact", body="Most founders sleep six hours.")], flags=[])


def patch_render(monkeypatch, intro_seconds=4.0):
    calls = []
    lengths = {"intro": intro_seconds, "outro": 3.0}

    def fake_speak(text, voice_id, out):
        out.write_bytes(b"mp3")
        return [], lengths["intro" if "intro" in out.name else "outro"]

    def fake_render(workdir, moment, out, **kw):
        calls.append({"workdir": workdir, "moment": moment, "offline": os.environ.get("MUSUBI_CLIPS_OFFLINE"), **kw})
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(b"mp4")
        return out
    monkeypatch.setattr(writing, "write_layer", fake_layer)
    monkeypatch.setattr(voice, "speak", fake_speak)
    monkeypatch.setattr(clipper, "render_one", fake_render)
    return calls


def test_make_clips_turns_planned_into_drafts(d, cfg_with_podcast, fetched_video, monkeypatch):
    calls = patch_render(monkeypatch)
    captions = {}

    def fake_caption(page, about, credits, previous):
        captions.update(about=about, credits=credits, previous=previous)
        return "New caption"
    monkeypatch.setattr(writing, "write_caption", fake_caption)
    clips_pipeline.make_clips(d, cfg_with_podcast, fetched_video)
    clip = d.execute("select * from clips where video_id='vid3'").fetchone()
    assert clip["status"] == "draft" and clip["file_key"] == f"clips/{clip['id']}.mp4"
    assert store.exists(clip["file_key"]) and clip["caption"] == "New caption"
    assert json.loads(clip["layer"])["cards"][0]["title"] == "Fact"
    assert captions["credits"] == ["🎙️ Video vid3 via @podofficial"]
    assert captions["about"].startswith("Burnout") and "old caption" in captions["previous"]
    call = calls[0]
    assert call["offline"] == "1" and call["workdir"] == config.HOME / "work" / "vid3"
    assert (call["workdir"] / "transcript.json").exists()
    assert call["theme"] == cfg_with_podcast.pages["podcastbawaal"].theme and call["music"] is None
    assert call["intro"]["seconds"] == 4.0 and call["outro"]["text"] == "Rest is part of the work"
    assert call["moment"]["cards"] == [{"at": 120.0, "title": "Fact", "body": "Most founders sleep six hours.", "hold": 4}]
    assert status(d, "vid3")["status"] == "cut"


def test_long_intro_fails_only_that_clip(d, cfg_with_podcast, fetched_video, monkeypatch):
    calls = patch_render(monkeypatch, intro_seconds=8.0)
    monkeypatch.setattr(writing, "write_caption", lambda *a: "c")
    clips_pipeline.make_clips(d, cfg_with_podcast, fetched_video)
    clip = d.execute("select status, reason from clips where video_id='vid3'").fetchone()
    assert tuple(clip) == ("failed", "layer too long") and calls == []
    assert status(d, "vid3")["status"] == "cut"


# --- step ---

def test_step_fails_a_video_whose_pick_breaks(d, cfg_with_podcast, prepared_video, monkeypatch):
    def broken(*a):
        raise RuntimeError("claude said no")
    monkeypatch.setattr(writing, "pick_moments", broken)
    clips_pipeline.step(d, cfg_with_podcast)
    assert tuple(status(d, "vid1")) == ("failed", "claude said no")
    assert store.exists("jobs/fetch.json")


def test_an_engine_failure_fails_the_clip_and_the_run_goes_on(d, cfg_with_podcast, fetched_video, monkeypatch):
    real = clipper.render_one
    patch_render(monkeypatch)
    monkeypatch.setattr(writing, "write_caption", lambda *a: "c")

    def engine_exits(*a, **k):
        raise SystemExit("hyperframes render failed")
    monkeypatch.setattr(clipper, "_render_one", engine_exits)
    monkeypatch.setattr(clipper, "render_one", real)
    clips_pipeline.make_clips(d, cfg_with_podcast, fetched_video)
    clip = d.execute("select status, reason from clips where video_id='vid3'").fetchone()
    assert tuple(clip) == ("failed", "hyperframes render failed")
    assert status(d, "vid3")["status"] == "cut"


def test_links_only_go_to_clip_pages(d, cfg_with_podcast, local_store):
    with pytest.raises(ValueError, match="links only go to clip pages"):
        clips_pipeline.add_link(d, cfg_with_podcast, "https://youtu.be/eee", "billikalesh", "ok")
    assert status(d, "eee") is None


def test_a_full_queue_picks_and_prepares_nothing(d, cfg_with_podcast, prepared_video, monkeypatch):
    add_video(d, "n1", "new")
    for _ in range(7):
        add_clip(d, "podcastbawaal", "draft")
    monkeypatch.setattr(writing, "pick_moments", lambda *a: pytest.fail("picked with a full queue"))
    clips_pipeline.step(d, cfg_with_podcast)
    assert store.get_json("jobs/fetch.json")["prepare"] == []
    assert status(d, "vid1")["status"] == "prepared"
