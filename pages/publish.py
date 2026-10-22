import random
from datetime import datetime, timedelta

from pages import accounts, ig, schedule, store
from pages import db as dbm

PAUSE_SUBCODES = {2207050, 2207051}
TOKEN_CODES = {190}
MAX_ATTEMPTS = 3
STUCK = timedelta(minutes=15)


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
    row = db.execute("select source_id from source_videos where video_id = ?", (clip["video_id"],)).fetchone()
    src = cfg.sources.get(row["source_id"]) if row else None
    return [src.instagram] if src and src.collab_ok and src.instagram else []


def _permitted(db, cfg, clip) -> bool:
    if clip["kind"] != "clip" or clip["video_id"] is None:
        return True
    row = db.execute("select source_id, note from source_videos where video_id = ?", (clip["video_id"],)).fetchone()
    return bool(row and (row["source_id"] in cfg.sources or row["note"]))


def publish_due(db, cfg, now: datetime) -> None:
    stuck = (now - STUCK).isoformat()
    due = db.execute("select id from clips where (status = 'scheduled' and scheduled_at <= ?) "
                     "or (status = 'publishing' and scheduled_at <= ?) order by scheduled_at",
                     (now.isoformat(), stuck)).fetchall()
    for (cid,) in due:
        # Re-read each time: an earlier clip may have paused the page or invalidated its token.
        clip = db.execute("select * from clips where id = ? and status in ('scheduled', 'publishing')",
                          (cid,)).fetchone()
        page = _live_pages(db, now).get(clip["page"]) if clip else None
        if not page:
            continue
        try:
            if not _permitted(db, cfg, clip):
                db.execute("update clips set status = 'failed', reason = 'source no longer permitted' where id = ?",
                           (cid,))
                db.commit()
                dbm.event(db, clip["page"], "source_withdrawn", f"clip {cid}")
                continue
            if clip["status"] == "scheduled":
                # No bursts after downtime: a late clip, or one too close to the last post, gets a fresh slot.
                last = db.execute("select max(published_at) from clips where page = ?", (clip["page"],)).fetchone()[0]
                late = now - datetime.fromisoformat(clip["scheduled_at"]) > timedelta(minutes=60)
                if late or (last and now - datetime.fromisoformat(last) < timedelta(hours=3)):
                    _reslot(db, cfg, clip, now)
                    continue
            # Claim it, so a second runner (or a later tick) never publishes it too. A stuck claim
            # (crash mid-publish) is re-claimed after STUCK and resolved through its container.
            cur = db.execute("update clips set status = 'publishing', scheduled_at = ? where id = ? and status = ? "
                             "and scheduled_at = ?", (now.isoformat(), cid, clip["status"], clip["scheduled_at"]))
            db.commit()
            if cur.rowcount != 1:
                continue
            clip = db.execute("select * from clips where id = ?", (cid,)).fetchone()
            try:
                _publish_one(db, cfg, clip, page, now)
            finally:  # not published and not failed: back in the queue
                db.execute("update clips set status = 'scheduled' where id = ? and status = 'publishing'", (cid,))
                db.commit()
        except ig.IGError as e:
            _handle_error(db, clip, e, now)
        except Exception as e:  # noqa: BLE001 - one bad clip must not stop the others
            _handle_error(db, clip, ig.IGError(-1, None, f"{type(e).__name__}: {e}"), now)


def _reslot(db, cfg, clip, now: datetime) -> None:
    page = cfg.pages[clip["page"]]
    taken = [datetime.fromisoformat(r[0]) for r in db.execute(
        "select coalesce(published_at, scheduled_at) from clips where page = ? and id != ? "
        "and (published_at is not null or scheduled_at is not null)", (clip["page"], clip["id"]))]
    slot = schedule.pick_slot(clip["page"], now, taken, page.window, page.daily_target)
    if slot is None:  # no room in two weeks: back to approved for schedule_approved to retry
        db.execute("update clips set status = 'approved', scheduled_at = null where id = ?", (clip["id"],))
    else:
        db.execute("update clips set scheduled_at = ? where id = ?", (slot.isoformat(), clip["id"]))
    db.commit()
    dbm.event(db, clip["page"], "rescheduled", f"clip {clip['id']} -> {slot.isoformat() if slot else 'approved'}")


def _publish_one(db, cfg, clip, page, now: datetime) -> None:
    uid, token = page["ig_user_id"], page["token"]
    container_id = clip["container_id"]
    if container_id:  # an earlier attempt got this far: Instagram may already have posted it
        status = ig.container(container_id, token).get("status_code")
        if status == "PUBLISHED":
            _published(db, clip, None, now)
            dbm.event(db, clip["page"], "published_without_id", f"clip {clip['id']} container {container_id}")
            return
        if status != "FINISHED":
            container_id = None
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
    if not container_id:
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
    # Record the post before anything else can fail, or the retry path would publish it twice.
    _published(db, clip, media_id, now)
    dbm.event(db, clip["page"], "published", f"clip {clip['id']} media {media_id}")
    try:
        permalink = ig.media(media_id, token).get("permalink")
        db.execute("update clips set permalink = ? where id = ?", (permalink, clip["id"]))
        db.commit()
    except Exception as e:  # noqa: BLE001 - the post is live; a missing permalink must never retry it
        dbm.event(db, clip["page"], "permalink_failed", f"clip {clip['id']}: {e}")


def _published(db, clip, media_id, now: datetime) -> None:
    db.execute("update clips set status = 'published', media_id = ?, published_at = ? where id = ?",
               (media_id, now.isoformat(), clip["id"]))
    db.execute("update pages set first_post_at = coalesce(first_post_at, ?) where handle = ?",
               (now.isoformat(), clip["page"]))
    db.commit()


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
