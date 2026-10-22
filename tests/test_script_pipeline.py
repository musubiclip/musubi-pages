import io
import json
import shutil
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from engine import clipper
from pages import config, llm, script_pipeline, store, voice, writing
from pages.script_pipeline import Shot
from pages.writing import Beat, Script


def w(word, start, end):
    return {"word": word, "start": start, "end": end}


def make_script(n=6):
    return Script(idea="why cats purr", title="Why cats purr", hook_text="Cats purr for a reason",
                  beats=[Beat(line=f"line {i} has five words", shot_query=f"cat {i}") for i in range(n)],
                  claims=["Cats purr at 25 to 150 Hz"], flags=[])


def test_script_prompt_lists_used_ideas_and_validates_beats(cfg, monkeypatch):
    seen = {}
    monkeypatch.setattr(llm, "ask", lambda p, s: (seen.setdefault("p", p), make_script(4))[1])
    with pytest.raises(ValueError, match="5 to 7 beats"):
        writing.write_script(cfg.pages["billikalesh"], ["why cats knead"])
    assert "why cats knead" in seen["p"]


def vid(i, seconds):
    return i, seconds


def fake_http_json(monkeypatch, pexels, pixabay):
    monkeypatch.setenv("PEXELS_KEY", "pk")
    monkeypatch.setenv("PIXABAY_KEY", "xk")
    seen = []

    def urlopen(req, timeout=None):
        seen.append(req)
        if "pexels.com" in req.full_url:
            assert req.get_header("Authorization") == "pk"
            body = {"videos": [{"id": i, "duration": s, "url": f"https://www.pexels.com/video/{i}/",
                                "user": {"name": f"P{i}"},
                                "video_files": [{"height": 720, "link": f"https://p/{i}/720.mp4"},
                                                {"height": 1920, "link": f"https://p/{i}/1920.mp4"},
                                                {"height": 1280, "link": f"https://p/{i}/1280.mp4"}]}
                               for i, s in pexels]}
        else:
            assert "key=xk" in req.full_url and "safesearch=true" in req.full_url
            body = {"hits": [{"id": i, "duration": s, "pageURL": f"https://pixabay.com/videos/{i}/", "user": f"X{i}",
                              "videos": {"large": {"url": "", "height": 0},
                                         "medium": {"url": f"https://x/{i}/m.mp4", "height": 720}}}
                             for i, s in pixabay]}
        return io.BytesIO(json.dumps(body).encode())

    monkeypatch.setattr(script_pipeline.urllib.request, "urlopen", urlopen)
    return seen


def test_footage_prefers_pexels_skips_used_and_short(monkeypatch):
    fake_http_json(monkeypatch, pexels=[vid(1, 3), vid(2, 9), vid(3, 9)], pixabay=[])
    shot = script_pipeline.search_footage("cat stretching", 6.0, used={"pexels:2"})
    assert (shot.provider, shot.id, shot.licence) == ("pexels", "3", "Pexels License")
    assert shot.download_url == "https://p/3/1280.mp4" and shot.author == "P3"


def test_footage_falls_back_to_pixabay_then_none(monkeypatch):
    fake_http_json(monkeypatch, pexels=[vid(1, 3)], pixabay=[vid(7, 10)])
    shot = script_pipeline.search_footage("dog", 6.0, used=set())
    assert (shot.provider, shot.id, shot.download_url) == ("pixabay", "7", "https://x/7/m.mp4")
    assert shot.licence == "Pixabay Content License"
    assert script_pipeline.search_footage("dog", 6.0, used={"pixabay:7"}) is None


def test_missing_key_skips_that_provider(monkeypatch):
    seen = fake_http_json(monkeypatch, pexels=[vid(1, 9)], pixabay=[vid(7, 10)])
    monkeypatch.delenv("PEXELS_KEY")
    assert script_pipeline.search_footage("dog", 6.0, used=set()).provider == "pixabay"
    assert all("pexels" not in r.full_url for r in seen)


def test_beat_spans_cover_the_voiceover_in_order():
    words = [w("Ever", 0, .3), w("wondered?", .3, .9), w("Cats", 1.0, 1.3), w("purr.", 1.3, 2.0)]
    beats = [Beat(line="Ever wondered?", shot_query="a"), Beat(line="Cats purr.", shot_query="b")]
    assert script_pipeline.beat_spans(words, beats) == [(0.0, 1.0), (1.0, 2.0)]


def patch_reel(monkeypatch, seconds=30.0, shots=True):
    seen = {}
    monkeypatch.setenv("PEXELS_KEY", "k")
    script = make_script()
    monkeypatch.setattr(writing, "write_script", lambda page, used: script)
    step = seconds / 30

    def speak(text, voice_id, out):
        out.write_bytes(b"mp3")
        return [w(x, round(i * step, 3), round((i + 1) * step, 3)) for i, x in enumerate(text.split())], seconds

    monkeypatch.setattr(voice, "speak", speak)
    n = iter(range(100))
    monkeypatch.setattr(script_pipeline, "search_footage", lambda q, s, used: Shot(
        "pexels", str(next(n)), "https://p/x.mp4", "https://pexels.com/v", "Ann", "Pexels License", 9) if shots else None)
    monkeypatch.setattr(script_pipeline, "_download", lambda url, path: path.write_bytes(b"v") and path)

    def montage(paths, spans, mp3, out):
        seen["montage"] = (paths, spans)
        out.write_bytes(b"mp4")
        return out

    monkeypatch.setattr(script_pipeline, "montage", montage)

    def render_one(workdir, moment, out, **kw):
        seen["render"] = (workdir, moment, kw)
        Path(out).write_bytes(b"reel")
        return out

    monkeypatch.setattr(clipper, "render_one", render_one)
    monkeypatch.setattr(writing, "write_caption", lambda page, about, credits, prev: "Cats.\n\n" + "\n".join(credits))
    return seen


def clip(d, i):
    return d.execute("select * from clips where id = ?", (i,)).fetchone()


@pytest.fixture
def cfg():
    c = config.load()
    c.pages["billikalesh"].pipeline = "script"  # billikalesh runs animals now; these tests run a script page
    return c


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setattr(script_pipeline.config, "HOME", tmp_path / "home")
    return tmp_path / "home"


def test_make_reel_stores_claims_credits_and_a_draft(d, cfg, local_store, home, monkeypatch):
    seen = patch_reel(monkeypatch)
    i = script_pipeline.make_reel(d, cfg, cfg.pages["billikalesh"])
    row = clip(d, i)
    assert (row["status"], row["kind"]) == ("draft", "script"), row["reason"]
    assert len(json.loads(row["credits"])) == 6
    assert json.loads(row["script"])["claims"] == ["Cats purr at 25 to 150 Hz"]
    assert "Footage: Ann / pexels" in row["caption"]
    assert store.exists(row["file_key"])
    workdir, moment, kw = seen["render"]
    assert workdir == home / "work" / f"script-{i}"
    assert (moment["start"], moment["end"], moment["hook_text"]) == (0.0, 30.0, "Cats purr for a reason")
    meta = json.loads((workdir / "meta.json").read_text())
    assert meta["transcript_source"] == "polly" and meta["duration"] == 31.0
    assert json.loads((workdir / "transcript.json").read_text())["source"] == "polly"
    assert kw["music"] is None and kw["theme"] == cfg.pages["billikalesh"].theme
    assert len(seen["montage"][1]) == 6


def test_script_too_long_fails_the_reel(d, cfg, local_store, home, monkeypatch):
    patch_reel(monkeypatch, seconds=55.0)
    row = clip(d, script_pipeline.make_reel(d, cfg, cfg.pages["billikalesh"]))
    assert row["status"] == "failed" and "script length" in row["reason"]


@pytest.fixture(autouse=True)
def good_video(monkeypatch):
    """Stub files written by tests probe as 999 s of video unless named broken."""
    monkeypatch.setattr(script_pipeline, "_video_seconds", lambda p: 0.0 if "broken" in Path(p).read_bytes().decode(errors="ignore") else 999.0)


def test_a_broken_stored_shot_reuses_its_neighbour(d, cfg, local_store, home, tmp_path, monkeypatch):
    seen = patch_reel(monkeypatch, shots=False)
    i = script_pipeline.make_reel(d, cfg, cfg.pages["billikalesh"])
    cc_footage(tmp_path, i, {0, 1, 2, 3, 4, 5})
    bad = tmp_path / "bad.mp4"
    bad.write_bytes(b"broken")
    store.put(f"footage/cc/{i}-2.mp4", bad)
    script_pipeline.step(d, cfg)
    row = clip(d, i)
    assert row["status"] == "draft", row["reason"]
    paths = [p.name for p in seen["montage"][0]]
    assert paths[2] == paths[1]
    assert "https://youtu.be/2" not in row["credits"]


def test_reel_waits_for_cc_footage_then_finishes(d, cfg, local_store, home, tmp_path, monkeypatch):
    patch_reel(monkeypatch, shots=False)
    script_pipeline.step(d, cfg)
    row = d.execute("select * from clips where page = 'billikalesh'").fetchone()
    assert row["status"] == "waiting_footage"
    jobs = store.get_json("jobs/cc.json")
    assert [j["key"] for j in jobs] == [f"{row['id']}-{b}" for b in range(6)]
    assert jobs[0]["query"] == "cat 0" and jobs[0]["seconds"] > 0

    src = tmp_path / "cc.mp4"
    src.write_bytes(b"v")
    for j in jobs:
        store.put(f"footage/cc/{j['key']}.mp4", src)
        store.put_json(f"footage/cc/{j['key']}.json", {"page_url": "https://youtu.be/a", "author": "Bo", "licence": "CC BY"})
    script_pipeline.step(d, cfg)
    row = clip(d, row["id"])
    assert row["status"] == "draft"
    assert "Footage: Bo (CC BY) https://youtu.be/a" in row["caption"]
    assert not {j["key"] for j in jobs} & {j["key"] for j in store.get_json("jobs/cc.json")}


def cc_footage(tmp_path, i, have):
    src = tmp_path / "cc.mp4"
    src.write_bytes(b"v")
    for b in range(6):
        if b in have:
            store.put(f"footage/cc/{i}-{b}.mp4", src)
            store.put_json(f"footage/cc/{i}-{b}.json", {"page_url": f"https://youtu.be/{b}", "author": "Bo", "licence": "CC BY"})
        else:
            store.put(f"footage/cc/{i}-{b}.none", src)


def test_a_none_beat_reuses_the_previous_shot_and_credits_once(d, cfg, local_store, home, tmp_path, monkeypatch):
    seen = patch_reel(monkeypatch, shots=False)
    i = script_pipeline.make_reel(d, cfg, cfg.pages["billikalesh"])
    cc_footage(tmp_path, i, {0, 1, 3, 4, 5})
    script_pipeline.step(d, cfg)
    row = clip(d, i)
    assert row["status"] == "draft", row["reason"]
    paths = [p.name for p in seen["montage"][0]]
    assert len(paths) == 6 and paths[2] == paths[1]
    credits = [c["credit"] for c in json.loads(row["credits"])]
    assert len(credits) == 5 == len(set(credits))
    assert row["caption"].count("https://youtu.be/1") == 1


def test_a_none_first_beat_reuses_the_next_shot(d, cfg, local_store, home, tmp_path, monkeypatch):
    seen = patch_reel(monkeypatch, shots=False)
    i = script_pipeline.make_reel(d, cfg, cfg.pages["billikalesh"])
    cc_footage(tmp_path, i, {1, 2, 3, 4, 5})
    script_pipeline.step(d, cfg)
    assert clip(d, i)["status"] == "draft"
    paths = [p.name for p in seen["montage"][0]]
    assert paths[0] == paths[1]


def test_all_beats_none_fails_the_waiting_reel(d, cfg, local_store, home, tmp_path, monkeypatch):
    patch_reel(monkeypatch, shots=False)
    i = script_pipeline.make_reel(d, cfg, cfg.pages["billikalesh"])
    cc_footage(tmp_path, i, set())
    script_pipeline.step(d, cfg)
    row = clip(d, i)
    assert row["status"] == "failed" and row["reason"] == "no footage for any beat"


def test_step_makes_no_new_reel_while_one_waits(d, cfg, local_store, home, monkeypatch):
    patch_reel(monkeypatch, shots=False)
    script_pipeline.step(d, cfg)
    script_pipeline.step(d, cfg)
    assert d.execute("select count(*) from clips where page = 'billikalesh'").fetchone()[0] == 1


def test_inactive_page_makes_no_reel(d, cfg, local_store, home, monkeypatch):
    patch_reel(monkeypatch)
    cfg.pages["billikalesh"].active = False
    script_pipeline.step(d, cfg)
    assert d.execute("select count(*) from clips where page = 'billikalesh'").fetchone()[0] == 0


def test_reel_waiting_over_3_days_fails(d, cfg, local_store, home, monkeypatch):
    patch_reel(monkeypatch, shots=False)
    i = script_pipeline.make_reel(d, cfg, cfg.pages["billikalesh"])
    d.execute("update clips set created_at = ? where id = ?", ((datetime.now(UTC) - timedelta(days=4)).isoformat(), i))
    script_pipeline.step(d, cfg)
    row = clip(d, i)
    assert row["status"] == "failed" and row["reason"] == "no CC footage after 3 days"


def test_waiting_reel_shots_count_as_used(d, cfg, local_store, home, monkeypatch):
    patch_reel(monkeypatch)
    d.execute("insert into clips (page, kind, status, script) values ('billikalesh', 'script', 'waiting_footage', ?)",
              (json.dumps({"idea": "dogs", "shots": [{"provider": "pexels", "id": "7"}]}),))
    seen = []
    monkeypatch.setattr(script_pipeline, "search_footage", lambda q, s, used: seen.append(set(used)))
    script_pipeline.make_reel(d, cfg, cfg.pages["billikalesh"])
    assert "pexels:7" in seen[0]


def fake_ytdlp(monkeypatch, entries, rc=0):
    """entries: a list for every search, or a dict of search query -> list."""
    calls = []

    def run(cmd, **kw):
        calls.append(cmd)
        if "-J" in cmd:
            found = entries if isinstance(entries, list) else entries.get(cmd[-1].split("search_query=")[1].split("&")[0], [])
            if kw.get("check") and rc:
                raise subprocess.CalledProcessError(rc, cmd)
            return subprocess.CompletedProcess(cmd, rc, json.dumps({"entries": found}), "ERROR: Sign in to confirm your age.")
        Path(cmd[cmd.index("-o") + 1]).write_bytes(b"broken" if "stub" in cmd[-1] else b"v")
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(script_pipeline.subprocess, "run", run)
    return calls


CC = {"id": "b", "duration": 60, "license": "Creative Commons Attribution license (reuse allowed)",
      "webpage_url": "https://youtu.be/b", "uploader": "Bee"}


def test_cc_search_skips_bad_results_and_reads_json_despite_exit_1(local_store, home, monkeypatch):
    calls = fake_ytdlp(monkeypatch, [CC], rc=1)
    assert script_pipeline.fetch_cc({"key": "5-2", "query": "cat", "seconds": 6.0}) is True
    assert "--ignore-errors" in calls[0]


def test_cc_search_with_no_json_fails(local_store, home, monkeypatch):
    def run(cmd, **kw):
        return subprocess.CompletedProcess(cmd, 1, "", "ERROR: boom")

    monkeypatch.setattr(script_pipeline.subprocess, "run", run)
    with pytest.raises(Exception):
        script_pipeline.fetch_cc({"key": "5-3", "query": "cat", "seconds": 6.0})


def test_cc_search_retries_with_the_first_two_words(local_store, home, monkeypatch):
    calls = fake_ytdlp(monkeypatch, {"sleepy+cat+on+sofa": [], "sleepy+cat": [CC]})
    assert script_pipeline.fetch_cc({"key": "5-4", "query": "sleepy cat on sofa", "seconds": 6.0}) is True
    assert len([c for c in calls if "-J" in c]) == 2
    assert store.exists("footage/cc/5-4.mp4") and not store.exists("footage/cc/5-4.none")


def test_cc_search_refuses_a_video_without_a_cc_licence(local_store, home, monkeypatch):
    calls = fake_ytdlp(monkeypatch, [{"id": "a", "duration": 60, "license": "Standard YouTube License",
                                      "webpage_url": "https://youtu.be/a", "uploader": "A"}])
    assert script_pipeline.fetch_cc({"key": "5-0", "query": "cat", "seconds": 6.0}) is False
    assert store.exists("footage/cc/5-0.none") and not store.exists("footage/cc/5-0.mp4")
    assert len(calls) == 1


def test_cc_search_downloads_the_middle_of_a_long_enough_cc_video(local_store, home, monkeypatch):
    calls = fake_ytdlp(monkeypatch, [
        {"id": "s", "duration": 8, "license": "Creative Commons Attribution license (reuse allowed)"},
        {"id": "b", "duration": 60, "license": "Creative Commons Attribution license (reuse allowed)",
         "webpage_url": "https://youtu.be/b", "uploader": "Bee"}])
    assert script_pipeline.fetch_cc({"key": "5-1", "query": "cat", "seconds": 6.0}) is True
    assert "EgIwAQ%253D%253D" in calls[0][-1]
    assert calls[1][calls[1].index("--download-sections") + 1] == "*27.0-33.0"
    assert store.get_json("footage/cc/5-1.json") == {
        "page_url": "https://youtu.be/b", "author": "Bee", "licence": "Creative Commons Attribution license (reuse allowed)"}
    assert store.exists("footage/cc/5-1.mp4")


def test_cc_download_skips_a_stub_and_uses_the_next_result(local_store, home, monkeypatch):
    calls = fake_ytdlp(monkeypatch, [{**CC, "webpage_url": "https://youtu.be/stub"}, CC])
    assert script_pipeline.fetch_cc({"key": "5-5", "query": "cat", "seconds": 6.0}) is True
    dl = calls[1]
    assert "--force-keyframes-at-cuts" in dl and "height<=1080" in dl[dl.index("-f") + 1]
    assert store.get_json("footage/cc/5-5.json")["page_url"] == "https://youtu.be/b"


def test_cc_download_all_stubs_writes_none(local_store, home, monkeypatch):
    fake_ytdlp(monkeypatch, [{**CC, "webpage_url": "https://youtu.be/stub"}])
    assert script_pipeline.fetch_cc({"key": "5-6", "query": "cat", "seconds": 6.0}) is False
    assert store.exists("footage/cc/5-6.none") and not store.exists("footage/cc/5-6.mp4")


@pytest.mark.slow
def test_montage_is_vertical_and_as_long_as_the_voice(tmp_path):
    assert shutil.which("ffmpeg")
    shots = []
    for i, size in enumerate(["640x360", "360x640"]):
        p = tmp_path / f"s{i}.mp4"
        subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", f"testsrc2=size={size}:rate=30:duration=3",
                        str(p)], check=True)
        shots.append(p)
    mp3 = tmp_path / "v.mp3"
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "sine=frequency=440:duration=3", str(mp3)], check=True)
    out = script_pipeline.montage(shots, [(0.0, 1.5), (1.5, 3.0)], mp3, tmp_path / "m.mp4")
    probe = json.loads(subprocess.run(["ffprobe", "-v", "error", "-show_entries",
                                       "stream=codec_type,width,height:format=duration", "-of", "json", str(out)],
                                      capture_output=True, text=True, check=True).stdout)
    v = next(s for s in probe["streams"] if s["codec_type"] == "video")
    assert (v["width"], v["height"]) == (1080, 1920)
    assert abs(float(probe["format"]["duration"]) - 4.0) < 0.2


def test_old_clip_credits_on_a_script_page_are_ignored(d, cfg, local_store, home, monkeypatch):
    d.execute("insert into clips (page, kind, status, credits) values ('billikalesh', 'clip', 'draft', ?)",
              (json.dumps(["🎙️ Some podcast"]),))
    assert script_pipeline._used(d, "billikalesh") == set()


def test_a_recent_failure_waits_an_hour(d, cfg, local_store, home, monkeypatch):
    patch_reel(monkeypatch)
    d.execute("insert into clips (page, kind, status, created_at) values ('billikalesh', 'script', 'failed', ?)",
              ((datetime.now(UTC) - timedelta(minutes=10)).isoformat(),))
    script_pipeline.step(d, cfg)
    assert d.execute("select count(*) from clips").fetchone()[0] == 1
    d.execute("update clips set created_at = ?", ((datetime.now(UTC) - timedelta(hours=2)).isoformat(),))
    script_pipeline.step(d, cfg)
    assert d.execute("select count(*) from clips").fetchone()[0] == 2


def test_no_stock_keys_sends_every_beat_to_cc(d, cfg, local_store, home, monkeypatch):
    patch_reel(monkeypatch)
    monkeypatch.delenv("PEXELS_KEY", raising=False)
    monkeypatch.delenv("PIXABAY_KEY", raising=False)
    monkeypatch.setattr(script_pipeline, "search_footage", lambda q, s, used: None)
    row = clip(d, script_pipeline.make_reel(d, cfg, cfg.pages["billikalesh"]))
    assert row["status"] == "waiting_footage"
    assert {s["provider"] for s in json.loads(row["script"])["shots"]} == {"cc"}
    events = d.execute("select kind, detail from events where page = 'billikalesh'").fetchall()
    assert [tuple(e) for e in events] == [("no_stock_keys", "using Creative Commons footage")]
