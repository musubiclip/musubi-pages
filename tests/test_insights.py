from datetime import UTC, datetime, timedelta

from helpers import add_clip
from pages import insights

T = datetime(2026, 11, 2, 6, 0, tzinfo=UTC)


def connect(d, handle="billikalesh"):
    d.execute("update pages set ig_user_id = '1789', token = 'tok', token_expires_at = ? where handle = ?",
              ((T + timedelta(days=60)).isoformat(), handle))
    d.commit()


def dues(d):
    return [r[0] for r in d.execute("select due from insights order by fetched_at")]


def test_insights_fetched_once_at_each_point(d, fake_ig):
    connect(d)
    cid = add_clip(d, "billikalesh", "published", media_id="m1", published_at=T.isoformat())
    insights.fetch_due(d, T + timedelta(hours=2))
    assert dues(d) == ["1h"]
    insights.fetch_due(d, T + timedelta(hours=25))
    assert dues(d) == ["1h", "24h"]
    insights.fetch_due(d, T + timedelta(hours=25))
    assert fake_ig.insight_calls == ["m1", "m1"]
    row = d.execute("select * from insights where clip_id = ? and due = '24h'", (cid,)).fetchone()
    assert (row["views"], row["saves"], row["avg_watch_ms"]) == (100, 2, 4000)


def test_no_insights_for_disconnected_page(d, fake_ig):
    add_clip(d, "billikalesh", "published", media_id="m1", published_at=T.isoformat())
    insights.fetch_due(d, T + timedelta(days=8))
    assert fake_ig.insight_calls == []


def test_daily_account_once_per_ist_day(d, cfg, fake_ig):
    connect(d)
    fake_ig.me_result = {**fake_ig.me_result, "followers_count": 42}
    cfg.api["follower_type_views"] = True
    insights.daily_account(d, cfg, T)
    insights.daily_account(d, cfg, T + timedelta(hours=1))
    rows = d.execute("select * from account_daily").fetchall()
    assert [tuple(r) for r in rows] == [("billikalesh", "2026-11-01", 42, 1000, 800)]


def test_daily_account_without_split(d, cfg, fake_ig):
    connect(d)
    cfg.api["follower_type_views"] = False
    insights.daily_account(d, cfg, T)
    assert tuple(d.execute("select views, views_non_follower from account_daily").fetchone()) == (1000, None)


def test_page_metrics_median_and_non_follower_share(d):
    for n, views in enumerate([100, 300, 5000]):
        cid = add_clip(d, "billikalesh", "published", published_at=(T - timedelta(days=n + 8)).isoformat())
        d.execute("insert into insights (clip_id, due, fetched_at, views) values (?, '24h', ?, 1)", (cid, T.isoformat()))
        d.execute("insert into insights (clip_id, due, fetched_at, views) values (?, '7d', ?, ?)",
                  (cid, T.isoformat(), views))
    add_clip(d, "billikalesh", "published", published_at=(T - timedelta(days=40)).isoformat())
    d.execute("insert into account_daily values ('billikalesh', '2026-10-30', 0, 1000, 800)")
    d.commit()
    assert insights.page_metrics(d, "billikalesh", T) == {"reels": 3, "median_views": 300,
                                                          "non_follower_share": 0.8}
    assert insights.page_metrics(d, "podcastbawaal", T) == {"reels": 0, "median_views": None,
                                                            "non_follower_share": None}
