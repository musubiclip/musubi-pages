import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from pages import config

# Times are ISO 8601 UTC text; JSON blobs are text columns.
SCHEMA = """
create table if not exists pages (
    handle text primary key, ig_user_id text, token text, token_expires_at text, token_refreshed_at text,
    paused_at text, pause_reason text, first_post_at text, status_checked_at text, recommendable text
);
create table if not exists source_videos (
    id integer primary key, source_id text, page text, video_id text unique, url text, title text,
    published text, status text, note text, created_at text
);
create table if not exists clips (
    id integer primary key, page text, video_id text, kind text, start real, end real, moment text,
    layer text, script text, credits text, file_key text, caption text, status text, reason text,
    scheduled_at text, container_id text, media_id text, permalink text, trial integer,
    attempts integer default 0, created_at text, published_at text
);
create table if not exists insights (
    clip_id integer, due text, fetched_at text, views integer, reach integer, likes integer,
    comments integer, saves integer, shares integer, avg_watch_ms integer, primary key (clip_id, due)
);
create table if not exists account_daily (
    page text, day text, followers integer, views integer, views_non_follower integer, primary key (page, day)
);
create table if not exists events (
    id integer primary key, page text, at text, kind text, detail text
);
"""

QUEUE_LOW = 7


def connect(path: Path | None = None) -> sqlite3.Connection:
    path = Path(path or config.HOME / "pages.db")
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path)
    db.row_factory = sqlite3.Row
    db.execute("pragma journal_mode=wal")
    db.executescript(SCHEMA)
    return db


def add_pages(db, cfg) -> None:
    db.executemany("insert or ignore into pages (handle) values (?)", [(h,) for h in cfg.pages])
    db.commit()


def event(db, page: str | None, kind: str, detail: str) -> None:
    db.execute("insert into events (page, at, kind, detail) values (?, ?, ?, ?)",
               (page, datetime.now(UTC).isoformat(), kind, detail))
    db.commit()


def queue_size(db, page: str) -> int:
    return db.execute("select count(*) from clips where page = ? and status in "
                      "('planned', 'draft', 'approved', 'scheduled')", (page,)).fetchone()[0]
