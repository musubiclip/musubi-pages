import tempfile
from datetime import UTC, datetime
from pathlib import Path

from pages import store


def add_clip(d, page, status, **cols):
    n = d.execute("select coalesce(max(id), 0) + 1 from clips").fetchone()[0]
    row = {"page": page, "status": status, "kind": "clip", "caption": "caption", "file_key": f"clips/{n}.mp4",
           "created_at": datetime.now(UTC).isoformat(), "attempts": 0, **cols}
    cur = d.execute(f"insert into clips ({', '.join(row)}) values ({', '.join('?' * len(row))})", list(row.values()))
    d.commit()
    return cur.lastrowid


def put_prepared(local_store, video_id, info, language="en", transcript=None):
    transcript = transcript or {"language": language, "source": "youtube", "segments": [
        {"start": 0.0, "end": 3.0, "text": "Hello there.",
         "words": [{"word": "Hello", "start": 0.0, "end": 0.5}, {"word": "there.", "start": 0.5, "end": 1.0}]}]}
    base = f"work/{video_id}/"
    store.put_json(base + "meta.json", {"title": f"Video {video_id}", "url": f"https://www.youtube.com/watch?v={video_id}",
                                        "duration": 3600, "language": language, "transcript_source": "youtube"})
    store.put_json(base + "transcript.json", transcript)
    with tempfile.TemporaryDirectory() as tmp:
        txt = Path(tmp) / "transcript.txt"
        txt.write_text("".join(f"[{s['start']}-{s['end']}] {s['text']}\n" for s in transcript["segments"]))
        store.put(base + "transcript.txt", txt)
    store.put_json(base + "source-audio.info.json", info)
