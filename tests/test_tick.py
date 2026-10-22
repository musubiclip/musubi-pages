from datetime import UTC, datetime, timedelta

import pytest

from helpers import add_clip
from pages import store, tick

T = datetime(2026, 11, 2, 6, 0, tzinfo=UTC)


def test_backup_once_per_day(d, local_store):
    tick.backup(d, T)
    tick.backup(d, T + timedelta(hours=10))   # 21:30 IST, same day
    assert store.keys("backups/") == ["backups/pages-2026-11-02.db"]


def test_media_deleted_thirty_days_after_posting(d, local_store, tmp_path):
    f = tmp_path / "v.mp4"
    f.write_bytes(b"v")
    old = add_clip(d, "tech_bawaal", "published", published_at=(T - timedelta(days=31)).isoformat())
    new = add_clip(d, "tech_bawaal", "published", published_at=(T - timedelta(days=29)).isoformat())
    for cid in (old, new):
        store.put(f"clips/{cid}.mp4", f)
    tick.delete_old_media(d, T)
    assert not store.exists(f"clips/{old}.mp4") and store.exists(f"clips/{new}.mp4")
    keys = dict(d.execute("select id, file_key from clips").fetchall())
    assert keys == {old: None, new: f"clips/{new}.mp4"}


def test_one_failing_step_does_not_stop_the_others(d, cfg, monkeypatch, local_store):
    publish = pytest.importorskip("pages.publish")
    accounts = pytest.importorskip("pages.accounts")
    from pages import insights
    ran = []

    def boom(*a):
        raise RuntimeError("boom")
    monkeypatch.setattr(publish, "schedule_approved", boom)
    monkeypatch.setattr(publish, "publish_due", lambda *a: ran.append("publish_due"))
    monkeypatch.setattr(insights, "fetch_due", lambda *a: ran.append("fetch_due"))
    monkeypatch.setattr(insights, "daily_account", lambda *a: ran.append("daily_account"))
    monkeypatch.setattr(accounts, "refresh_tokens", lambda *a: ran.append("refresh_tokens"))
    monkeypatch.setattr(tick, "backup", lambda *a: ran.append("backup"))
    monkeypatch.setattr(tick, "delete_old_media", lambda *a: ran.append("delete_old_media"))
    tick.tick(d, cfg, T)
    assert ran == ["publish_due", "fetch_due", "daily_account", "refresh_tokens", "backup", "delete_old_media"]
    detail = d.execute("select detail from events where kind = 'tick_failed'").fetchone()[0]
    assert detail == "schedule_approved: boom"
