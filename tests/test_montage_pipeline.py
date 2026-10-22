import json

import pytest

from engine import clipper
from helpers import add_clip, put_prepared
from pages import clips_pipeline, config, llm, publish, store
from pages import montage_pipeline as mp


@pytest.fixture(autouse=True)
def home(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "HOME", tmp_path / "home")
    monkeypatch.delenv("MUSUBI_CLIPS_OFFLINE", raising=False)


# --- format mix ---

def test_formats_mix_by_their_weights(d, cfg):
    page = cfg.pages["tech_bawaal"]
    assert page.formats == {"clip": 2, "montage": 1, "rapidfire": 1}
    made = []
    for _ in range(12):
        kind = mp.next_format(d, page, ("clip", "montage", "rapidfire"))
        made.append(kind)
        add_clip(d, "tech_bawaal", "draft", kind=kind)
    assert made.count("clip") == 6 and made.count("montage") == 3 and made.count("rapidfire") == 3
    assert all(a != b or a == "clip" for a, b in zip(made, made[1:]))  # the formats interleave


def test_a_source_offers_only_its_own_formats(d, cfg):
    page = cfg.pages["tech_bawaal"]
    for _ in range(4):
        add_clip(d, "tech_bawaal", "draft", kind="clip")
    assert mp.next_format(d, page, ("clip", "montage")) == "montage"
    assert mp.next_format(d, page, ("clip", "rapidfire")) == "rapidfire"
    assert mp.next_format(d, cfg.pages["podcastbawaal"], ("clip", "rapidfire")) == "clip"  # no formats: clips only


def test_config_rejects_an_unknown_format(tmp_path):
    p = tmp_path / "pages.toml"
    p.write_text((config.ROOT / "pages.toml").read_text().replace("formats = {clip = 2,", "formats = {reel = 1, clip = 2,"))
    with pytest.raises(ValueError, match="formats"):
        config.load(p)


# --- rapid fire lines ---

SENTENCES = [{"start": 10.0 * i, "end": 10.0 * i + 3.5, "text": f"Sentence {i}."} for i in range(20)]


def L(start, end):
    return mp.Line(start=start, end=end, text="x")


def test_rapid_fire_lines_must_be_whole_sentences_of_2_to_5_seconds():
    good = [L(10, 13.5), L(30.1, 33.5), L(50, 53.5), L(70, 73.4), L(90, 93.5)]
    assert mp.line_problems(good, SENTENCES) == []
    assert mp.snapped(good, SENTENCES)[1] == {"start": 30.0, "end": 33.5, "text": "x"}
    mid = [L(10, 13.5), L(31.5, 33.5), L(50, 53.5), L(70, 73.4), L(90, 93.5)]
    assert any("not the start of a sentence" in p for p in mp.line_problems(mid, SENTENCES))
    cut = [L(10, 12.0), L(30, 33.5), L(50, 53.5), L(70, 73.4), L(90, 93.5)]
    assert any("not the end of a sentence" in p for p in mp.line_problems(cut, SENTENCES))
    joined = [{"start": 10.0, "end": 16.5, "text": "two"}] + SENTENCES  # two sentences in one line: 6.5 s is too long
    assert any("lasts 6.5 s" in p for p in mp.line_problems([L(10, 16.5)], joined))


def test_rapid_fire_needs_4_to_6_lines_that_never_overlap():
    three = [L(10, 13.5), L(30, 33.5), L(50, 53.5)]
    assert any("4 to 6 lines" in p for p in mp.line_problems(three, SENTENCES))
    seven = [L(10.0 * i, 10.0 * i + 3.5) for i in range(1, 8)]
    assert any("4 to 6 lines" in p for p in mp.line_problems(seven, SENTENCES))
    twice = [L(10, 13.5), L(10, 13.5), L(50, 53.5), L(70, 73.5)]
    assert any("overlaps" in p for p in mp.line_problems(twice, SENTENCES))
    short = [{"start": 10.0 * i, "end": 10.0 * i + 2.2, "text": "s"} for i in range(20)]
    four = [L(10.0 * i, 10.0 * i + 2.2) for i in range(1, 5)]
    assert any("run 8.8 s together" in p for p in mp.line_problems(four, short))


def test_fetch_moments_cover_every_line_and_survive_the_engine_checks():
    lines = [{"start": 100.0, "end": 103.0}, {"start": 104.5, "end": 108.0}, {"start": 300.0, "end": 304.0},
             {"start": 600.0, "end": 602.5}]
    moments = mp.fetch_moments(lines, "A headline of a good length for the reel")
    assert clipper.moment_problems(moments) == []
    words = [{"word": f"w{i}" + ("." if i % 4 == 3 else ""), "start": i * 0.5, "end": i * 0.5 + 0.4} for i in range(1400)]
    kept = clipper.tidy_clips(moments, words, mp.LINES[1])
    assert len(kept) == len(moments) == 3  # the first two lines share a span
    for line in lines:  # each line lies inside a span's section (sections add SECTION_PAD each side)
        assert any(m["start"] - clipper.SECTION_PAD <= line["start"] and line["end"] <= m["end"] + clipper.SECTION_PAD
                   for m in kept)


def test_visual_picks_are_checked():
    shots = [mp.Shot(video="a", start=2.0 * i, end=2.0 * i + 1.5) for i in range(10)]
    pick = mp.VisualPick(shots=shots, headline="This robot arm carves a marble statue in three hours",
                         accent=["marble"], text_beats=["ZERO HUMAN HANDS", "PURE PRECISION"], flags=[])
    assert mp.visual_problems(pick, {"a": 60}) == []
    bad = pick.model_copy(update={"shots": shots[:5] + [mp.Shot(video="a", start=1, end=5)],
                                  "accent": ["granite"], "text_beats": ["THIS LINE IS FAR TOO LONG HERE"]})
    problems = " | ".join(mp.visual_problems(bad, {"a": 60}))
    for want in ("8 to 15 shots", "1 to 3 seconds", "repeats footage", "accent", "at most 5 words", "2 to 4 text beats"):
        assert want in problems


# --- the flow ---

def short_sentences():
    """A word every half second, a sentence every 8 words (3.9 s), for 10 minutes."""
    words = [{"word": f"w{i}" + ("." if i % 8 == 7 else ""), "start": i * 0.5, "end": i * 0.5 + 0.4} for i in range(1200)]
    return {"language": "en", "source": "youtube", "segments": clipper.group_segments(words)}


def test_pick_plans_a_rapid_fire_reel_when_the_mix_wants_one(d, cfg, local_store, monkeypatch):
    put_prepared(local_store, "pod1", {"channel": "Pod", "license": "Creative Commons Attribution license"},
                 transcript=short_sentences())
    d.execute("insert into source_videos (source_id, page, video_id, url, title, status) values "
              "(null, 'tech_bawaal', 'pod1', 'https://www.youtube.com/watch?v=pod1', 'Pod talk', 'prepared')")
    for _ in range(2):
        add_clip(d, "tech_bawaal", "draft", kind="clip")
    lines = [mp.Line(start=s, end=s + 9.8, text="w") for s in (0.0, 0.0)]  # first answer: too long, twice the same
    good = [mp.Line(start=s, end=s + 3.9, text="w") for s in (100.0, 200.0, 300.0, 400.0, 500.0)]
    answers = iter([mp.RapidPick(lines=lines, headline="Founder says AI will change every job in India", accent=["AI"], flags=[]),
                    mp.RapidPick(lines=good, headline="Founder says AI will change every job in India", accent=["AI"], flags=[])])
    monkeypatch.setattr(llm, "ask", lambda *a, **k: next(answers))
    row = d.execute("select * from source_videos where video_id = 'pod1'").fetchone()
    clips_pipeline.pick(d, cfg, row)
    clip = d.execute("select * from clips where video_id = 'pod1'").fetchone()
    assert clip["kind"] == "rapidfire" and clip["status"] == "planned"
    assert [l["start"] for l in json.loads(clip["moment"])["lines"]] == [100.0, 200.0, 300.0, 400.0, 500.0]
    assert len(store.get_json("work/pod1/moments.json")) == 5
    assert d.execute("select status from source_videos where video_id = 'pod1'").fetchone()[0] == "picked"
    clips_pipeline.write_jobs(d, cfg)
    assert store.get_json("jobs/fetch.json")["sections"][0]["count"] == mp.LINES[1]


def test_make_clips_renders_a_rapid_fire_in_speech_mode(d, cfg, local_store, monkeypatch):
    from test_clips_pipeline import long_transcript
    put_prepared(local_store, "pod2", {"channel": "Pod", "license": "Creative Commons Attribution license"},
                 transcript=long_transcript())
    d.execute("insert into source_videos (source_id, page, video_id, url, title, status) values "
              "(null, 'tech_bawaal', 'pod2', 'https://www.youtube.com/watch?v=pod2', 'Pod talk', 'fetched')")
    moment = {"headline": "Founder says AI will change every job in India", "accent": ["AI"], "flags": [],
              "lines": [{"start": 10.0 + 10 * i, "end": 13.8 + 10 * i, "text": "w"} for i in range(4)]}
    add_clip(d, "tech_bawaal", "planned", kind="rapidfire", video_id="pod2", moment=json.dumps(moment), caption=None, file_key=None)
    seen = {}
    monkeypatch.setattr(clipper, "video_section", lambda w, m, c, s: (w / "sections" / "0.00-700.00.mp4", 5.0))

    def render(segments, out, **kw):
        seen.update(kw, segments=segments)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(b"mp4")
        return out
    monkeypatch.setattr(mp.montage, "render_montage", render)
    monkeypatch.setattr(mp.writing, "write_caption", lambda page, about, credits, previous: "caption\n" + credits[0])
    row = d.execute("select * from source_videos where video_id = 'pod2'").fetchone()
    clips_pipeline.make_clips(d, cfg, row)
    clip = d.execute("select * from clips where video_id = 'pod2'").fetchone()
    assert clip["status"] == "draft", clip["reason"]
    assert seen["mode"] == "speech" and len(seen["segments"]) == 4
    assert seen["segments"][0]["start"] == 5.0 and seen["segments"][0]["words"][0]["start"] == 5.0
    assert "🎙️ Pod talk by Pod (CC BY)" in clip["caption"]


def test_a_rapid_fire_needs_its_sources_permission_to_publish(d, cfg):
    d.execute("insert into source_videos (source_id, page, video_id, status) values ('gone', 'tech_bawaal', 'v9', 'cut')")
    cid = add_clip(d, "tech_bawaal", "scheduled", kind="rapidfire", video_id="v9")
    assert not publish._permitted(d, cfg, d.execute("select * from clips where id = ?", (cid,)).fetchone())
