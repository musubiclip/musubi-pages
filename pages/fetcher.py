"""Mac side: the YouTube work (`pages fetch`). Reads jobs from the store, writes results back."""
import json
import subprocess
import sys
from datetime import UTC, datetime

from pages import config, store  # noqa: F401  config first: it sets MUSUBI_CLIPS_DIR for the engine
from engine import clipper

PREPARED = ("meta.json", "transcript.json", "transcript.txt", "source-audio.info.json")


def _published(entry) -> str | None:
    if entry.get("timestamp"):
        return datetime.fromtimestamp(entry["timestamp"], UTC).date().isoformat()
    d = entry.get("upload_date")
    return f"{d[:4]}-{d[4:6]}-{d[6:8]}" if d else None


def watch(job) -> None:
    out = subprocess.run(["yt-dlp", "--flat-playlist", "-J", "--playlist-end", "15", "--extractor-args",
                          "youtubetab:approximate_date", job["url"].rstrip("/") + "/videos"],
                         capture_output=True, text=True, check=True).stdout
    store.put_json(f"inbox/{job['source']}.json", [
        {"video_id": e["id"], "url": f"https://www.youtube.com/watch?v={e['id']}", "title": e.get("title"),
         "published": _published(e)} for e in json.loads(out).get("entries") or []])


def prepare(job) -> bool:
    vid, base = job["video_id"], f"work/{job['video_id']}/"
    if store.exists(base + "transcript.json") or store.exists(base + "error.txt"):
        return False
    workdir = clipper.work_root() / vid
    try:
        clipper.prepare(job["url"])
    except SystemExit as e:  # the engine exits when YouTube has no captions: skip the video for good
        workdir.mkdir(parents=True, exist_ok=True)
        (workdir / "error.txt").write_text(str(e.code))
        store.put(base + "error.txt", workdir / "error.txt")
        return True
    # anything else (429s, bot checks) raises: run_jobs counts it failed and the job is retried next run
    for f in [*(workdir / n for n in PREPARED), *sorted(workdir.glob("captions.*.json3"))]:
        store.put(base + f.name, f)
    return True


def sections(job) -> bool:
    vid, base = job["video_id"], f"work/{job['video_id']}/"
    if store.exists(base + "sections.done"):
        return False
    workdir = clipper.work_root() / vid
    for key in store.keys(base):
        if not key.startswith(base + "sections/") and not (workdir / key[len(base):]).exists():
            store.get(key, workdir / key[len(base):])
    clipper.fetch_sections(workdir, job["count"])
    for f in sorted((workdir / "sections").glob("*.mp4")):
        if not f.name.endswith(".part.mp4"):
            store.put(base + "sections/" + f.name, f)
    store.put_json(base + "sections.done", True)
    return True


def run_jobs() -> dict:
    jobs = store.get_json("jobs/fetch.json", {})
    done = {"watch": 0, "prepare": 0, "sections": 0, "cc": 0, "animals": 0, "failed": 0}
    cc = store.get_json("jobs/cc.json", [])
    if cc:
        from pages.script_pipeline import fetch_cc
    animals = store.get_json("jobs/animals.json", [])
    if animals:
        from pages.animals_pipeline import fetch_animals
    work = [("watch", watch, jobs.get("watch", [])), ("prepare", prepare, jobs.get("prepare", [])),
            ("sections", sections, jobs.get("sections", [])), ("cc", lambda j: fetch_cc(j) or True, cc),
            ("animals", lambda j: fetch_animals(j), animals)]
    for kind, fn, items in work:
        for job in items:
            # One bad job must not block the rest: it stays queued and would fail first every run.
            try:
                if fn(job) is not False:
                    done[kind] += 1
            except (SystemExit, Exception) as e:  # the engine sys.exits on some failures
                print(f"{kind} failed for {job}: {e}", file=sys.stderr, flush=True)
                done["failed"] += 1
    return done
