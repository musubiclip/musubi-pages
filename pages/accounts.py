from datetime import datetime, timedelta

from pages import db as dbm
from pages import ig


def connect(db, handle: str, token: str, now: datetime) -> None:
    me = ig.me(token)
    if me["username"].lower() != handle.lower():
        raise ValueError(f"token is for @{me['username']}, not @{handle}")
    db.execute("update pages set ig_user_id = ?, token = ?, token_expires_at = ?, token_refreshed_at = ? "
               "where handle = ?", (me["user_id"], token, (now + timedelta(days=60)).isoformat(), now.isoformat(),
                                    handle))
    db.commit()
    dbm.event(db, handle, "connected", f"@{me['username']} ({me['user_id']})")


def pause(db, handle: str, reason: str, now: datetime) -> None:
    db.execute("update pages set paused_at = ?, pause_reason = ? where handle = ?", (now.isoformat(), reason, handle))
    db.execute("update clips set status = 'approved', scheduled_at = null where page = ? and status = 'scheduled'",
               (handle,))
    db.commit()
    dbm.event(db, handle, "paused", reason)


def unpause(db, handle: str, now: datetime) -> None:
    db.execute("update pages set paused_at = null, pause_reason = null where handle = ?", (handle,))
    db.commit()
    dbm.event(db, handle, "unpaused", now.isoformat())


def refresh_tokens(db, now: datetime) -> None:
    rows = db.execute("select handle, token, token_expires_at, token_refreshed_at from pages "
                      "where token is not null").fetchall()
    for r in rows:
        if datetime.fromisoformat(r["token_expires_at"]) <= now:
            continue
        if r["token_refreshed_at"] and now - datetime.fromisoformat(r["token_refreshed_at"]) < timedelta(days=7):
            continue
        try:
            token, expires_in = ig.refresh(r["token"])
        except ig.IGError as e:
            dbm.event(db, r["handle"], "token_refresh_failed", str(e))
            continue
        db.execute("update pages set token = ?, token_expires_at = ?, token_refreshed_at = ? where handle = ?",
                   (token, (now + timedelta(seconds=expires_in)).isoformat(), now.isoformat(), r["handle"]))
        db.commit()
        dbm.event(db, r["handle"], "token_refreshed", "")
