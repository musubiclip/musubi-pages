import statistics
from datetime import datetime, timedelta

from pages import ig
from pages.schedule import IST

DUE = {"1h": timedelta(hours=1), "24h": timedelta(hours=24), "72h": timedelta(hours=72), "7d": timedelta(days=7)}


def _connected(db, now: datetime):
    return db.execute("select * from pages where token is not null and token_expires_at > ?",
                      (now.isoformat(),)).fetchall()


def fetch_due(db, now: datetime) -> None:
    for page in _connected(db, now):
        clips = db.execute("select id, media_id, published_at from clips where page = ? and status = 'published' "
                           "and media_id is not null and published_at is not null", (page["handle"],)).fetchall()
        for clip in clips:
            done = {r[0] for r in db.execute("select due from insights where clip_id = ?", (clip["id"],))}
            age = now - datetime.fromisoformat(clip["published_at"])
            for due in [k for k, wait in DUE.items() if age >= wait and k not in done]:
                m = ig.media_insights(clip["media_id"], page["token"])
                db.execute("insert into insights values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                           (clip["id"], due, now.isoformat(), m["views"], m["reach"], m["likes"], m["comments"],
                            m["saved"], m["shares"], m["ig_reels_avg_watch_time"]))
                db.commit()


def daily_account(db, cfg, now: datetime) -> None:
    today = now.astimezone(IST).date()
    yesterday = today - timedelta(days=1)
    for page in _connected(db, now):
        if db.execute("select 1 from account_daily where page = ? and day = ?",
                      (page["handle"], yesterday.isoformat())).fetchone():
            continue
        followers = ig.me(page["token"])["followers_count"]
        v = ig.account_views(page["ig_user_id"], page["token"], yesterday, today)
        non_follower = v["non_follower"] if cfg.api.get("follower_type_views") else None
        db.execute("insert into account_daily values (?, ?, ?, ?, ?)",
                   (page["handle"], yesterday.isoformat(), followers, v["total"], non_follower))
        db.commit()


def page_metrics(db, page: str, now: datetime) -> dict:
    since = now - timedelta(days=28)
    clips = [r[0] for r in db.execute("select id from clips where page = ? and status = 'published' "
                                      "and published_at >= ?", (page, since.isoformat()))]
    views = []
    for cid in clips:
        row = db.execute("select views from insights where clip_id = ? order by due = '7d' desc, fetched_at desc "
                         "limit 1", (cid,)).fetchone()
        if row and row[0] is not None:
            views.append(row[0])
    total, non = db.execute("select sum(views), sum(views_non_follower) from account_daily where page = ? "
                            "and day >= ? and views_non_follower is not null",
                            (page, since.astimezone(IST).date().isoformat())).fetchone()
    return {"reels": len(clips), "median_views": int(statistics.median(views)) if views else None,
            "non_follower_share": non / total if total else None}
