"""One-off API check (`pages verify-ig`). Creates containers but never publishes."""
import subprocess
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

from pages import config, ig, store


def _test_video(path: Path) -> None:
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error",
                    "-f", "lavfi", "-i", "testsrc2=size=1080x1920:rate=30:duration=5",
                    "-f", "lavfi", "-i", "sine=frequency=440:duration=5",
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(path)], check=True)


def run(db, handle: str) -> dict:
    page = db.execute("select ig_user_id, token from pages where handle = ?", (handle,)).fetchone()
    uid, token = page["ig_user_id"], page["token"]
    now = datetime.now(UTC)
    key = f"clips/verify-{now.strftime('%Y%m%dT%H%M%SZ')}.mp4"
    with tempfile.TemporaryDirectory() as tmp:
        video = Path(tmp) / "verify.mp4"
        _test_video(video)
        store.put(key, video)
    url = store.url(key, 6 * 3600)
    out = {}

    usage, total = ig.publishing_limit(uid, token)
    out["publishing_limit"] = {"usage": usage, "total": total}

    def create(**kw):
        return ig.create_reel(uid, token, url, "API check", thumb_offset_ms=1300, collaborators=[], **kw)

    # Drop one parameter at a time to find out which one the API refuses.
    try:
        cid = create(trial=True, ai_label=True)
        out["trial_params"] = out["ai_label"] = "accepted"
    except ig.IGError as e:
        out["trial_params"] = f"rejected: {e.message}"
        try:
            cid = create(trial=False, ai_label=True)
            out["ai_label"] = "accepted"
        except ig.IGError as e2:
            out["ai_label"] = f"rejected: {e2.message}"
            cid = create(trial=False, ai_label=False)

    try:
        out["copyright_check_status"] = ig.wait_container(cid, token, copyright=True).get("copyright_check_status")
    except ig.IGError as e:
        out["copyright_check_status"] = f"error: {e.message}"

    views = ig.account_views(uid, token, (now - timedelta(days=7)).date(), now.date())
    out["follower_type_views"] = views["follower"] is not None

    collab = next((s for s in config.load().sources.values() if s.collab_ok and s.instagram), None)
    if collab:
        try:
            ig.create_reel(uid, token, url, "API check", thumb_offset_ms=1300, trial=False,
                           collaborators=[collab.instagram], ai_label=True)
            out["collaborators"] = "accepted"
        except ig.IGError as e:
            out["collaborators"] = f"rejected: {e.message}"
    return out
