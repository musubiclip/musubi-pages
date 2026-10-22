import json
import subprocess
from pathlib import Path

import pytest

from engine import clipper
from helpers import add_clip
from pages import animals_pipeline as ap
from pages import config, llm, store, writing

INFO = {"id": "cat1", "title": "Cat vs cucumber", "channel": "Bee", "webpage_url": "https://www.youtube.com/watch?v=cat1",
        "license": "Creative Commons Attribution license (reuse allowed)", "duration": 120}


@pytest.fixture
def cfg():
    c = config.load()
    p = c.pages["tech_bawaal"]  # tech_bawaal is a clips page; these tests run an animals page
    p.pipeline, p.topics = "animals", "cats, dogs, wild animals and nature"
    p.queries = ["my cat", "cat playing", "kitten playing", "my dog", "dog playing", "puppy", "wildlife"]
    return c


@pytest.fixture(autouse=True)
def home(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "HOME", tmp_path / "home")
    monkeypatch.setenv("MUSUBI_CLIPS_DIR", str(tmp_path / "mac"))
    monkeypatch.delenv("MUSUBI_CLIPS_OFFLINE", raising=False)


def M(start, end, **kw):
    return ap.Moment(**{"start": start, "end": end, "title": "Cucumber jump", "hook_text": "She did not expect this cucumber at all",
                        "cards": [{"at": start + 2, "title": "Why", "body": "Cats startle at long shapes."}],
                        "flags": [], "hook": 4, "standalone": 4, "payoff": 4, "emotion": 4, **kw})


def downloaded(d, local_store, vid="cat1"):
    store.put_json(f"work/{vid}/source-audio.info.json", {**INFO, "id": vid})
    store.put_json(f"work/{vid}/source.mp4", "video")
    d.execute("insert into source_videos (source_id, page, video_id, url, title, status, note) values "
              "('cc_youtube', 'tech_bawaal', ?, ?, 'Cat vs cucumber', 'downloaded', 'CC BY')", (vid, INFO["webpage_url"]))
    d.commit()


def video(d, vid="cat1"):
    return d.execute("select * from source_videos where video_id = ?", (vid,)).fetchone()


# --- jobs and inbox ---

def test_jobs_rotate_queries_and_stop_while_a_video_is_in_progress(d, cfg, local_store):
    ap.write_jobs(d, cfg)
    assert store.get_json("jobs/animals.json") == [{"page": "tech_bawaal", "query": "my cat", "skip": []}]
    store.put_json("inbox/animals/none.json", {"none": True, "page": "tech_bawaal", "query": "my cat"})
    ap.take_inbox(d, cfg)
    ap.write_jobs(d, cfg)
    assert store.get_json("jobs/animals.json")[0]["query"] == "cat playing"
    store.put_json("inbox/animals/cat1.json", {"page": "tech_bawaal", "video_id": "cat1", "url": INFO["webpage_url"],
                                               "title": "Cat vs cucumber", "channel": "Bee", "license": INFO["license"]})
    ap.take_inbox(d, cfg)
    assert not store.keys("inbox/animals/")
    row = video(d)
    assert row["status"] == "downloaded" and row["source_id"] == "cc_youtube"
    assert INFO["license"] in row["note"] and "Bee" in row["note"] and INFO["webpage_url"] in row["note"]
    ap.write_jobs(d, cfg)
    assert store.get_json("jobs/animals.json") == []  # one video at a time
    d.execute("update source_videos set status = 'cut'")
    ap.write_jobs(d, cfg)
    assert store.get_json("jobs/animals.json") == [{"page": "tech_bawaal", "query": "kitten playing", "skip": ["cat1"]}]


def test_no_jobs_when_paused_or_the_queue_is_full(d, cfg, local_store):
    for _ in range(7):
        add_clip(d, "tech_bawaal", "draft")
    ap.write_jobs(d, cfg)
    assert store.get_json("jobs/animals.json") == []
    cfg.pages["tech_bawaal"].active = False
    d.execute("delete from clips")
    ap.write_jobs(d, cfg)
    assert store.get_json("jobs/animals.json") == []


# --- Mac side ---

def fake_ytdlp(monkeypatch, entries, seconds=120.0):
    calls = []

    def run(cmd, **kw):
        calls.append(cmd)
        if "-J" in cmd:
            return subprocess.CompletedProcess(cmd, 1, json.dumps({"entries": entries}), "ERROR: age")
        Path(cmd[cmd.index("-o") + 1]).write_bytes(b"v")
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(subprocess, "run", run)
    monkeypatch.setattr(ap, "_video_seconds", lambda p: seconds)
    return calls


def entry(vid, duration=120, license=INFO["license"]):
    return {"id": vid, "duration": duration, "license": license, "webpage_url": f"https://youtu.be/{vid}",
            "title": f"T {vid}", "uploader": "Bee"}


def test_fetch_keeps_the_first_unused_cc_video_of_sane_length(local_store, monkeypatch):
    calls = fake_ytdlp(monkeypatch, [entry("std", license="Standard YouTube License"), entry("short", 20),
                                     entry("long", 3600), entry("used"), entry("ok")])
    assert ap.fetch_animals({"page": "tech_bawaal", "query": "funny cat", "skip": ["used"]}) is True
    down = [c for c in calls if "-J" not in c]
    assert len(down) == 1 and down[0][-1] == "https://youtu.be/ok" and "--ignore-errors" in calls[0]
    assert down[0][down[0].index("-f") + 1] == ap.AV_FORMAT and "+ba" in ap.AV_FORMAT
    assert store.exists("work/ok/source.mp4")
    assert store.get_json("work/ok/source-audio.info.json")["license"] == INFO["license"]
    assert store.get_json("inbox/animals/ok.json") == {"page": "tech_bawaal", "video_id": "ok", "url": "https://youtu.be/ok",
                                                       "title": "T ok", "channel": "Bee", "license": INFO["license"]}
    # the server has not taken that yet: no second download
    assert ap.fetch_animals({"page": "tech_bawaal", "query": "funny cat", "skip": []}) is False


def test_fetch_skips_a_stub_download_and_reports_none(local_store, monkeypatch):
    fake_ytdlp(monkeypatch, [entry("a")], seconds=3.0)
    assert ap.fetch_animals({"page": "tech_bawaal", "query": "funny cat", "skip": []}) is False
    assert store.get_json("inbox/animals/none.json") == {"none": True, "page": "tech_bawaal", "query": "funny cat"}
    assert not store.exists("work/a/source.mp4")


def test_fetcher_runs_animal_jobs(local_store, monkeypatch):
    from pages import fetcher
    seen = []
    monkeypatch.setattr(ap, "fetch_animals", lambda job: seen.append(job) or True)
    store.put_json("jobs/animals.json", [{"page": "tech_bawaal", "query": "funny cat", "skip": []}])
    assert fetcher.run_jobs()["animals"] == 1 and seen[0]["query"] == "funny cat"


# --- pick ---

def test_keep_checks_length_bounds_cards_and_overlaps():
    kept = ap.keep([M(0, 10), M(100, 150), M(110, 130, hook=1), M(20, 50, hook=5), M(10, 40), M(60, 80),
                    M(150, 170), M(85, 100, hook_text="one two three four five six seven eight nine"),
                    M(85, 100, cards=[]), M(85, 100, cards=[{"at": 120, "title": "x", "body": "y"}])], 160, 3)
    # best first; too short, too long, past the end, long hook, no card, card outside and overlaps all go
    assert [(m.start, m.end) for m in kept] == [(20, 50), (60, 80), (110, 130)]


def test_contact_sheets_tile_stamped_frames(tmp_path):
    src = tmp_path / "s.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=size=640x360:rate=10:duration=40",
                    "-pix_fmt", "yuv420p", str(src)], check=True)
    sheets, every = ap.contact_sheets(src, 40, tmp_path / "sheets")
    assert every == 2 and len(sheets) == 2  # 20 frames: one full 4x4 sheet and one partly filled
    assert clipper.probe_size(sheets[0])[0] >= 4 * 320


def test_long_videos_get_at_most_twelve_sheets():
    every = max(ap.EVERY, round(1200 / (16 * 12) + 0.5))
    assert 1200 / every / 16 <= 12


def test_pick_sends_the_sheets_and_cuts_to_claude(cfg, tmp_path, monkeypatch):
    seen = {}
    monkeypatch.setattr(llm, "ask", lambda prompt, schema, images=None: (
        seen.update(prompt=prompt, images=images), ap.Moments(moments=[M(10, 30)]))[1])
    sheet = tmp_path / "sheet-01.png"
    got = ap.pick_moments(cfg.pages["tech_bawaal"], INFO, 120, [4.5, 12.25], [sheet], 2)
    assert got[0].start == 10 and seen["images"] == [sheet]
    assert "4.5, 12.2" in seen["prompt"] and "Cat vs cucumber" in seen["prompt"] and "15 to 30" in seen["prompt"]


# --- cut ---

@pytest.fixture
def fakes(monkeypatch, tmp_path):
    rendered = []
    monkeypatch.setattr(clipper, "duration_of", lambda v: 120.0)
    monkeypatch.setattr(clipper, "shot_cuts", lambda v, a, b: [9.8, 30.1])
    monkeypatch.setattr(ap, "contact_sheets", lambda v, dur, folder: ([folder / "sheet-01.png"], 2))
    monkeypatch.setattr(ap, "pick_moments", lambda *a: [M(10, 30), M(50, 80), M(55, 70), M(0, 5)])

    def render_one(workdir, moment, out, **kw):
        rendered.append((workdir, moment, kw))
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(b"mp4")
        return out
    monkeypatch.setattr(clipper, "render_one", render_one)
    monkeypatch.setattr(writing, "write_caption", lambda page, about, credits, prev: about + "\n\n" + "\n".join(credits))
    return rendered


def test_cut_renders_drafts_with_cards_music_and_the_cc_credit(d, cfg, local_store, fakes, monkeypatch):
    monkeypatch.setattr(ap, "clips_for", lambda duration, cap: cap)  # treat the fixture as a long video
    downloaded(d, local_store)
    ap.step(d, cfg)
    assert video(d)["status"] == "cut"
    rows = d.execute("select * from clips where video_id = 'cat1' order by id").fetchall()
    assert [(r["start"], r["end"], r["status"], r["kind"]) for r in rows] == [(10, 30, "draft", "clip"), (50, 80, "draft", "clip")]
    workdir, moment, kw = fakes[0]
    assert moment["cards"][0] == {"at": 12.0, "title": "Why", "body": "Cats startle at long shapes.", "hold": 4}
    assert kw == {"theme": cfg.pages["tech_bawaal"].theme, "intro": None, "outro": None, "music": None,
                  "hook_style": "headline", "brand_tag": "TECH BAWAAL"}
    meta = json.loads((workdir / "meta.json").read_text())
    assert meta["url"] == INFO["webpage_url"] and meta["path"] == str(workdir / "source.mp4") and meta["language"] == "en"
    assert json.loads((workdir / "transcript.json").read_text())["segments"] == []
    credit = "🎥 Cat vs cucumber by Bee (CC BY)"
    assert json.loads(rows[0]["credits"])[0]["text"] == credit and json.loads(rows[0]["credits"])[0]["url"] == INFO["webpage_url"]
    assert credit in rows[0]["caption"] and store.exists(rows[0]["file_key"])
    assert json.loads(rows[0]["layer"])["flags"] == []


def test_one_failed_render_fails_only_that_clip(d, cfg, local_store, fakes, monkeypatch):
    monkeypatch.setattr(ap, "clips_for", lambda duration, cap: cap)  # treat the fixture as a long video
    downloaded(d, local_store)
    real = clipper.render_one

    def flaky(workdir, moment, out, **kw):
        if moment["start"] == 50:
            raise RuntimeError("hyperframes render failed")
        return real(workdir, moment, out, **kw)
    monkeypatch.setattr(clipper, "render_one", flaky)
    ap.step(d, cfg)
    rows = d.execute("select status, reason from clips order by id").fetchall()
    assert [tuple(r) for r in rows] == [("draft", None), ("failed", "hyperframes render failed")]
    assert video(d)["status"] == "cut"


def test_no_usable_moment_skips_and_a_pick_error_fails_the_video(d, cfg, local_store, fakes, monkeypatch):
    downloaded(d, local_store)
    monkeypatch.setattr(ap, "pick_moments", lambda *a: [M(0, 5)])
    ap.step(d, cfg)
    assert tuple(video(d))[7:9] == ("skipped", "no usable moments")
    downloaded(d, local_store, "cat2")

    def boom(*a):
        raise llm.LLMError("limit")
    monkeypatch.setattr(ap, "pick_moments", boom)
    ap.step(d, cfg)
    assert video(d, "cat2")["status"] == "failed" and video(d, "cat2")["note"] == "limit"
    assert d.execute("select kind from events where page = 'tech_bawaal'").fetchone()[0] == "animals_failed"


def test_cli_work_runs_the_animals_step(monkeypatch, tmp_path):
    from pages import cli, clips_pipeline, script_pipeline
    ran = []
    monkeypatch.setenv("PAGES_HOME", str(tmp_path))
    monkeypatch.setattr(config, "HOME", tmp_path)
    for mod in (clips_pipeline, script_pipeline, ap):
        monkeypatch.setattr(mod, "step", lambda db, cfg, m=mod: ran.append(m.__name__))
    cli.main(["work"])
    assert ran == ["pages.clips_pipeline", "pages.script_pipeline", "pages.animals_pipeline"]


def test_reupload_titles_are_skipped():
    for t in ["TRY NOT TO LAUGH at These Funny Cats", "Cat Compilation 2026", "Funny Moments part 3", "Best of TikTok cats"]:
        assert ap.REUPLOAD.search(t), t
    for t in ["Satisfying Compilation of machines", "Amazing Machines Compilation", "Top 10 robots"]:
        assert ap.REUPLOAD.search(t), t
    for t in ["My cat Luna meets a cucumber", "Kitten plays with a ball of yarn", "How a CNC lathe cuts steel"]:
        assert not ap.REUPLOAD.search(t), t


def test_pick_prompt_skips_watermarks():
    assert "watermark" in ap.PICK_RULES and "another creator" in ap.PICK_RULES


def test_pick_prompt_is_page_neutral(cfg, monkeypatch):
    seen = {}
    monkeypatch.setattr(llm, "ask", lambda prompt, schema, images=None: (seen.update(prompt=prompt), ap.Moments(moments=[]))[1])
    page = cfg.pages["tech_bawaal"]
    page.topics = "gadgets and engineering explainers"
    ap.pick_moments(page, INFO, 120, [], [], 2)
    assert "@tech_bawaal" in seen["prompt"] and "gadgets and engineering explainers" in seen["prompt"]
    assert "cats" not in ap.PICK_RULES and "animal videos" not in ap.PICK_RULES
    assert "This is what happens when" in ap.HOOK_RULES["spotlight"] and "mechanism" in ap.PICK_RULES and "If animals appear" in ap.PICK_RULES
    # tech_bawaal is a headline page: a factual 6 to 14 word headline with accent words, not the 8 word teaser
    assert "news headline of 6 to 14 words" in seen["prompt"] and "hook_accent" in seen["prompt"]
    assert "at most 8 words" not in seen["prompt"]


def test_keep_holds_headlines_to_6_to_14_words():
    short, ok = M(0, 20, hook_text="Gear eats steel"), M(30, 50, hook_text="This gear destroyed a steel shredder in 3 seconds")
    assert ap.keep([short, ok], 120, 3, "headline") == [ok]
    assert ap.keep([short, ok], 120, 3) == [short]  # spotlight: at most 8 words


def test_cut_stores_the_cover_frame(d, cfg, local_store, fakes, monkeypatch):
    real = clipper.render_one

    def with_cover(workdir, moment, out, **kw):
        real(workdir, moment, out, **kw)
        from PIL import Image
        Image.new("RGB", (108, 192)).save(out.with_suffix(".jpg"))
        return out
    monkeypatch.setattr(clipper, "render_one", with_cover)
    downloaded(d, local_store)
    ap.step(d, cfg)
    row = d.execute("select id, cover_key from clips where status = 'draft'").fetchone()
    assert row["cover_key"] == f"clips/{row['id']}-cover.jpg" and store.exists(row["cover_key"])
    assert store.exists(f"clips/{row['id']}.jpg")


def test_any_page_with_queries_gets_jobs_whatever_its_pipeline(d, local_store):
    c = config.load()
    assert c.pages["tech_bawaal"].pipeline == "clips" and c.pages["tech_bawaal"].queries
    for p in c.pages.values():
        if p.handle != "tech_bawaal":
            p.queries = []
    ap.write_jobs(d, c)
    assert [j["page"] for j in store.get_json("jobs/animals.json")] == ["tech_bawaal"]
    c.pages["tech_bawaal"].queries = []
    ap.write_jobs(d, c)
    assert store.get_json("jobs/animals.json") == []


def test_visual_clips_stay_under_half_the_queue(d, cfg, local_store):
    d.execute("insert into source_videos (source_id, page, video_id, url, title, status) values "
              "('cc_youtube', 'tech_bawaal', 'v1', 'u', 't', 'cut')")
    d.commit()
    for _ in range(3):
        add_clip(d, "tech_bawaal", "draft")  # podcast clips
    ap.write_jobs(d, cfg)
    assert len(store.get_json("jobs/animals.json")) == 1
    for _ in range(4):  # 4 >= 7 / 2
        d.execute("insert into clips (page, video_id, kind, status) values ('tech_bawaal', 'v1', 'clip', 'draft')")
    d.execute("delete from clips where video_id != 'v1'")
    d.commit()
    assert ap.visual_queued(d, "tech_bawaal") == 4
    ap.write_jobs(d, cfg)
    assert store.get_json("jobs/animals.json") == []


def test_short_videos_give_one_clip():
    assert ap.clips_for(60, 3) == 1 and ap.clips_for(179, 3) == 1
    assert ap.clips_for(180, 3) == 3 and ap.clips_for(600, 2) == 2
