import random
from datetime import datetime, timedelta

from pages import accounts, ig, schedule, store
from pages import db as dbm

PAUSE_SUBCODES = {2207050, 2207051}
TOKEN_CODES = {190}
MAX_ATTEMPTS = 3


def _live_pages(db, now: datetime) -> dict:
    rows = db.execute("select * from pages where token is not null and paused_at is null").fetchall()
    return {r["handle"]: r for r in rows if datetime.fromisoformat(r["token_expires_at"]) > now}


def schedule_approved(db, cfg, now: datetime, rng=random) -> None:
    for handle in _live_pages(db, now):
        page = cfg.pages.get(handle)
        if not page:
            continue
        taken = [datetime.fromisoformat(r[0]) for r in db.execute(
            "select coalesce(published_at, scheduled_at) from clips where page = ? "
            "and (published_at is not null or scheduled_at is not null)", (handle,))]
        for (cid,) in db.execute("select id from clips where page = ? and status = 'approved' order by id",
                                 (handle,)).fetchall():
            slot = schedule.pick_slot(handle, now, taken, page.window, page.daily_target, rng)
            if slot is None:
                break
            taken.append(slot)
            db.execute("update clips set status = 'scheduled', scheduled_at = ? where id = ?", (slot.isoformat(), cid))
        db.commit()


def _collaborators(db, cfg, clip) -> list[str]:
    if not cfg.api.get("collaborators") or clip["video_id"] is None:
        return []
    row = db.execute("select source_id from source_videos where id = ?", (clip["video_id"],)).fetchone()
    src = cfg.sources.get(row["source_id"]) if row else None
    return [src.instagram] if src and src.collab_ok and src.instagram else []


def publish_due(db, cfg, now: datetime) -> None:
    due = db.execute("select id from clips where status = 'scheduled' and scheduled_at <= ? order by scheduled_at",
                     (now.isoformat(),)).fetchall()
    for (cid,) in due:
        # Re-read each time: an earlier clip may have paused the page or invalidated its token.
        clip = db.execute("select * from clips where id = ? and status = 'scheduled'", (cid,)).fetchone()
        page = _live_pages(db, now).get(clip["page"]) if clip else None
        if not page:
            continue
        try:
            _publish_one(db, cfg, clip, page, now)
        except ig.IGError as e:
            _handle_error(db, clip, e, now)


def _publish_one(db, cfg, clip, page, now: datetime) -> None:
    uid, token = page["ig_user_id"], page["token"]
    usage, total = ig.publishing_limit(uid, token)
    if usage >= total:
        return
    url = store.url(clip["file_key"], 6 * 3600)
    if not url.startswith("https://"):
        dbm.event(db, clip["page"], "bad_url", f"clip {clip['id']}: video URL is not https")
        return
    first = page["first_post_at"]
    trial = bool(cfg.api.get("trial_reels")) and (
        first is None or now < datetime.fromisoformat(first) + timedelta(days=7))
    container_id = ig.create_reel(uid, token, url, clip["caption"], thumb_offset_ms=1300, trial=trial,
                                  collaborators=_collaborators(db, cfg, clip), ai_label=True)
    db.execute("update clips set container_id = ?, trial = ? where id = ?", (container_id, int(trial), clip["id"]))
    db.commit()
    c = ig.wait_container(container_id, token, copyright=bool(cfg.api.get("copyright_check")))
    if cfg.api.get("copyright_check") and (c.get("copyright_check_status") or {}).get("matches_found"):
        db.execute("update clips set status = 'failed', reason = 'copyright match' where id = ?", (clip["id"],))
        db.commit()
        dbm.event(db, clip["page"], "copyright_match", f"clip {clip['id']}")
        return
    media_id = ig.publish(uid, token, container_id)
    permalink = ig.media(media_id, token).get("permalink")
    db.execute("update clips set status = 'published', media_id = ?, permalink = ?, published_at = ? where id = ?",
               (media_id, permalink, now.isoformat(), clip["id"]))
    db.execute("update pages set first_post_at = coalesce(first_post_at, ?) where handle = ?",
               (now.isoformat(), clip["page"]))
    db.commit()
    dbm.event(db, clip["page"], "published", f"clip {clip['id']} {permalink}")


def _handle_error(db, clip, e: ig.IGError, now: datetime) -> None:
    if e.subcode in PAUSE_SUBCODES:
        accounts.pause(db, clip["page"], f"Instagram error {e.code}/{e.subcode}: {e.message}", now)
    elif e.code in TOKEN_CODES:
        db.execute("update pages set token_expires_at = ? where handle = ?", (now.isoformat(), clip["page"]))
        db.commit()
        dbm.event(db, clip["page"], "token_invalid", e.message)
    else:
        attempts = clip["attempts"] + 1
        if attempts < MAX_ATTEMPTS:
            db.execute("update clips set attempts = ?, scheduled_at = ? where id = ?",
                       (attempts, (now + timedelta(minutes=15)).isoformat(), clip["id"]))
        else:
            db.execute("update clips set attempts = ?, status = 'failed', reason = ? where id = ?",
                       (attempts, e.message, clip["id"]))
        db.commit()
        dbm.event(db, clip["page"], "publish_error", f"clip {clip['id']}: {e}")
