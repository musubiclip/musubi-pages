"""Mac side: the YouTube work (`pages fetch`). Reads jobs from the store, writes results back."""
import json
import subprocess
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
    except SystemExit as e:  # the engine exits when YouTube has no captions
        workdir.mkdir(parents=True, exist_ok=True)
        (workdir / "error.txt").write_text(str(e.code))
        store.put(base + "error.txt", workdir / "error.txt")
        return True
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
    done = {"watch": 0, "prepare": 0, "sections": 0, "cc": 0}
    for job in jobs.get("watch", []):
        watch(job)
        done["watch"] += 1
    done["prepare"] = sum(prepare(job) for job in jobs.get("prepare", []))
    done["sections"] = sum(sections(job) for job in jobs.get("sections", []))
    cc = store.get_json("jobs/cc.json", [])
    if cc:
        from pages.script_pipeline import fetch_cc
        for job in cc:
            fetch_cc(job)
        done["cc"] = len(cc)
    return done
