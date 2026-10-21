import sqlite3
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

from pages import db as dbm
from pages import store
from pages.schedule import IST


def backup(db, now: datetime) -> None:
    key = f"backups/pages-{now.astimezone(IST).date().isoformat()}.db"
    if store.exists(key):
        return
    with tempfile.TemporaryDirectory() as tmp:
        f = Path(tmp) / "pages.db"
        out = sqlite3.connect(f)
        db.backup(out)
        out.close()
        store.put(key, f)


def delete_old_media(db, now: datetime) -> None:
    rows = db.execute("select id, file_key from clips where file_key is not null and published_at < ?",
                      ((now - timedelta(days=30)).isoformat(),)).fetchall()
    for cid, key in rows:
        store.delete(key)
        db.execute("update clips set file_key = null where id = ?", (cid,))
        db.commit()


def tick(db, cfg, now: datetime) -> None:
    from pages import accounts, insights, publish  # publish and accounts import ig; keep tick light to import
    steps = [("schedule_approved", lambda: publish.schedule_approved(db, cfg, now)),
             ("publish_due", lambda: publish.publish_due(db, cfg, now)),
             ("fetch_due", lambda: insights.fetch_due(db, now)),
             ("daily_account", lambda: insights.daily_account(db, cfg, now)),
             ("refresh_tokens", lambda: accounts.refresh_tokens(db, now)),
             ("backup", lambda: backup(db, now)),
             ("delete_old_media", lambda: delete_old_media(db, now))]
    for name, step in steps:
        try:
            step()
        except Exception as e:
            dbm.event(db, None, "tick_failed", f"{name}: {e}")
