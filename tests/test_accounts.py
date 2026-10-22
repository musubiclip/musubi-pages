from datetime import UTC, datetime, timedelta

import pytest

from pages import accounts, ig

NOW = datetime(2026, 10, 23, tzinfo=UTC)


def test_connect_stores_token_for_the_matching_account(d, monkeypatch):
    monkeypatch.setattr(ig, "me", lambda t: {"user_id": "1789", "username": "Tech_Bawaal"})
    accounts.connect(d, "tech_bawaal", "tok", now=NOW)
    row = d.execute("select * from pages where handle='tech_bawaal'").fetchone()
    assert (row["ig_user_id"], row["token"]) == ("1789", "tok")
    assert row["token_expires_at"] == "2026-12-22T00:00:00+00:00"
    assert row["token_refreshed_at"] == NOW.isoformat()
    assert d.execute("select count(*) from events where kind='connected'").fetchone()[0] == 1


def test_connect_refuses_a_token_for_another_account(d, monkeypatch):
    monkeypatch.setattr(ig, "me", lambda t: {"user_id": "5", "username": "musubi_clip"})
    with pytest.raises(ValueError, match="token is for @musubi_clip, not @tech_bawaal"):
        accounts.connect(d, "tech_bawaal", "tok", now=NOW)


def _connect(d, refreshed_days_ago):
    d.execute("update pages set token='old', token_expires_at=?, token_refreshed_at=? where handle='tech_bawaal'",
              ((NOW + timedelta(days=30)).isoformat(), (NOW - timedelta(days=refreshed_days_ago)).isoformat()))
    d.commit()


def test_refresh_is_weekly_and_records_the_new_expiry(d, fake_ig):
    _connect(d, 6)
    accounts.refresh_tokens(d, NOW)
    assert fake_ig.refreshed == []
    _connect(d, 8)
    accounts.refresh_tokens(d, NOW)
    row = d.execute("select * from pages where handle='tech_bawaal'").fetchone()
    assert fake_ig.refreshed == ["old"]
    assert row["token"] == "new-token"
    assert row["token_expires_at"] == (NOW + timedelta(seconds=5184000)).isoformat()
    assert row["token_refreshed_at"] == NOW.isoformat()


def test_refresh_failure_is_recorded(d, fake_ig, monkeypatch):
    _connect(d, 8)

    def boom(t):
        raise ig.IGError(190, None, "bad")
    monkeypatch.setattr(ig, "refresh", boom)
    accounts.refresh_tokens(d, NOW)
    assert d.execute("select count(*) from events where kind='token_refresh_failed'").fetchone()[0] == 1


def test_a_dead_token_on_refresh_asks_for_reconnect(d, fake_ig, monkeypatch):
    _connect(d, 8)

    def dead(t):
        raise ig.IGError(190, None, "Error validating access token")
    monkeypatch.setattr(ig, "refresh", dead)
    accounts.refresh_tokens(d, NOW)
    row = d.execute("select token_expires_at from pages where handle='tech_bawaal'").fetchone()
    assert row[0] == NOW.isoformat()
    assert d.execute("select count(*) from events where kind='token_invalid'").fetchone()[0] == 1


def test_connect_works_before_init_and_refuses_unknown_pages(d, monkeypatch):
    monkeypatch.setattr(ig, "me", lambda t: {"user_id": "1789", "username": "tech_bawaal"})
    d.execute("delete from pages")
    d.commit()
    accounts.connect(d, "tech_bawaal", "tok", now=NOW)
    assert d.execute("select token from pages where handle='tech_bawaal'").fetchone()[0] == "tok"
    with pytest.raises(ValueError, match="not in pages.toml"):
        accounts.connect(d, "musubi_clip", "tok", now=NOW)
