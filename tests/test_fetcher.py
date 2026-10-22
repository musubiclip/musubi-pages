import json
import subprocess

from engine import clipper
from pages import fetcher, store

NOTHING = {"watch": 0, "prepare": 0, "sections": 0, "cc": 0, "failed": 0}


def jobs(**kw):
    store.put_json("jobs/fetch.json", {"watch": [], "prepare": [], "sections": [], "cc_search": [], **kw})


def test_watch_writes_the_inbox(local_store, monkeypatch):
    seen = {}

    def fake_run(cmd, **kw):
        seen["cmd"] = cmd
        out = {"entries": [{"id": "a1", "title": "Ep 1", "timestamp": 1761350400},
                           {"id": "b2", "title": "Ep 2", "upload_date": "20261020"},
                           {"id": "c3", "title": "Ep 3"}]}
        return subprocess.CompletedProcess(cmd, 0, json.dumps(out), "")
    monkeypatch.setattr(fetcher.subprocess, "run", fake_run)
    jobs(watch=[{"source": "pod", "url": "https://www.youtube.com/@pod/"}])
    assert fetcher.run_jobs()["watch"] == 1
    assert seen["cmd"][-1] == "https://www.youtube.com/@pod/videos" and "--playlist-end" in seen["cmd"]
    inbox = store.get_json("inbox/pod.json")
    assert [(v["video_id"], v["published"]) for v in inbox] == [("a1", "2025-10-25"), ("b2", "2026-10-20"), ("c3", None)]
    assert inbox[0]["url"] == "https://www.youtube.com/watch?v=a1"


def test_prepare_uploads_work_files(local_store, tmp_path, monkeypatch):
    monkeypatch.setenv("MUSUBI_CLIPS_DIR", str(tmp_path / "work"))

    def fake_prepare(url):
        w = tmp_path / "work" / "abc"
        w.mkdir(parents=True)
        for name in ("meta.json", "transcript.json", "transcript.txt", "source-audio.info.json", "captions.hi-orig.json3"):
            (w / name).write_text("{}")
        (w / "source-audio.m4a").write_text("audio")
    monkeypatch.setattr(clipper, "prepare", fake_prepare)
    jobs(prepare=[{"video_id": "abc", "url": "https://youtu.be/abc"}])
    assert fetcher.run_jobs()["prepare"] == 1
    assert store.keys("work/abc/") == [f"work/abc/{n}" for n in (
        "captions.hi-orig.json3", "meta.json", "source-audio.info.json", "transcript.json", "transcript.txt")]


def test_no_captions_uploads_the_error(local_store, tmp_path, monkeypatch):
    monkeypatch.setenv("MUSUBI_CLIPS_DIR", str(tmp_path / "work"))

    def no_captions(url):
        raise SystemExit("no auto captions")
    monkeypatch.setattr(clipper, "prepare", no_captions)
    jobs(prepare=[{"video_id": "abc", "url": "https://youtu.be/abc"}])
    fetcher.run_jobs()
    assert (local_store / "work/abc/error.txt").read_text() == "no auto captions"


def test_sections_upload_then_mark_done(local_store, tmp_path, monkeypatch):
    monkeypatch.setenv("MUSUBI_CLIPS_DIR", str(tmp_path / "work"))
    store.put_json("work/abc/moments.json", [])
    store.put_json("work/abc/meta.json", {})

    def fake_sections(workdir, count):
        assert (workdir / "moments.json").exists() and count == 3
        (workdir / "sections").mkdir()
        (workdir / "sections" / "10.00-60.00.mp4").write_text("v")
        (workdir / "sections" / "70.00-90.00.part.mp4").write_text("v")
    monkeypatch.setattr(clipper, "fetch_sections", fake_sections)
    jobs(sections=[{"video_id": "abc", "url": "https://youtu.be/abc", "count": 3}])
    assert fetcher.run_jobs()["sections"] == 1
    assert store.exists("work/abc/sections/10.00-60.00.mp4") and store.exists("work/abc/sections.done")
    assert not store.exists("work/abc/sections/70.00-90.00.part.mp4")


def test_fetcher_skips_work_already_in_the_store(local_store, tmp_path, monkeypatch):
    monkeypatch.setenv("MUSUBI_CLIPS_DIR", str(tmp_path / "work"))
    store.put_json("work/abc/transcript.json", {})
    store.put_json("work/def/error.txt", "x")
    store.put_json("work/abc/sections.done", True)
    calls = []
    monkeypatch.setattr(clipper, "prepare", lambda url: calls.append(url))
    monkeypatch.setattr(clipper, "fetch_sections", lambda w, c: calls.append(w))
    jobs(prepare=[{"video_id": "abc", "url": "u"}, {"video_id": "def", "url": "u"}],
         sections=[{"video_id": "abc", "url": "u", "count": 3}])
    before = store.keys("")
    assert fetcher.run_jobs() == NOTHING
    assert fetcher.run_jobs() == NOTHING
    assert calls == [] and store.keys("") == before


def test_one_bad_prepare_never_blocks_the_rest(local_store, tmp_path, monkeypatch):
    monkeypatch.setenv("MUSUBI_CLIPS_DIR", str(tmp_path / "work"))
    calls = []

    def fake_prepare(url):
        calls.append(url)
        if url == "bad":
            raise RuntimeError("video is private")
        w = tmp_path / "work" / url
        w.mkdir(parents=True)
        for name in fetcher.PREPARED:
            (w / name).write_text("{}")
    monkeypatch.setattr(clipper, "prepare", fake_prepare)
    jobs(prepare=[{"video_id": "bad", "url": "bad"}, {"video_id": "good", "url": "good"}])
    done = fetcher.run_jobs()
    assert calls == ["bad", "good"] and done["failed"] == 1 and done["prepare"] == 1
    assert not (local_store / "work/bad/error.txt").exists()  # retried next run


def test_a_section_exit_never_stops_the_cc_jobs(local_store, tmp_path, monkeypatch):
    monkeypatch.setenv("MUSUBI_CLIPS_DIR", str(tmp_path / "work"))

    def exits(workdir, count):
        raise SystemExit("no section")
    monkeypatch.setattr(clipper, "fetch_sections", exits)
    from pages import script_pipeline
    monkeypatch.setattr(script_pipeline, "fetch_cc", lambda job: True)
    store.put_json("jobs/cc.json", [{"key": "k", "query": "cat", "seconds": 3}])
    jobs(sections=[{"video_id": "abc", "url": "u", "count": 3}])
    done = fetcher.run_jobs()
    assert done["failed"] == 1 and done["cc"] == 1


def test_no_jobs_file_does_nothing(local_store):
    assert fetcher.run_jobs() == NOTHING
