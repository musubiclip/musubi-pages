from datetime import UTC, datetime, timedelta

from helpers import add_clip

from pages import accounts, ig, publish, store

NOW = datetime(2026, 11, 2, 8, tzinfo=UTC)
P = "billikalesh"


def setup(d, monkeypatch, first_post_at=None):
    monkeypatch.setattr(store, "url", lambda k, s=3600: "https://example.test/" + k)
    d.execute("update pages set ig_user_id='1789', token='tok', token_expires_at=?, first_post_at=? where handle=?",
              ((NOW + timedelta(days=50)).isoformat(), first_post_at, P))
    d.commit()


def due(d, n=1):
    return [add_clip(d, P, "scheduled", scheduled_at=(NOW - timedelta(minutes=1)).isoformat()) for _ in range(n)]


def clip(d, cid):
    return d.execute("select * from clips where id=?", (cid,)).fetchone()


def page(d):
    return d.execute("select * from pages where handle=?", (P,)).fetchone()


def test_first_week_goes_out_as_a_trial_reel_with_the_ai_label(d, cfg, fake_ig, monkeypatch):
    setup(d, monkeypatch)
    cfg.api["trial_reels"] = True
    [c] = due(d)
    publish.publish_due(d, cfg, NOW)
    assert fake_ig.created[0]["trial"] is True and fake_ig.created[0]["ai_label"] is True
    assert fake_ig.created[0]["thumb_offset_ms"] == 1300
    row = clip(d, c)
    assert (row["status"], row["media_id"]) == ("published", "m1") and row["permalink"]
    assert page(d)["first_post_at"] == NOW.isoformat()


def test_after_seven_days_reels_are_not_trial(d, cfg, fake_ig, monkeypatch):
    setup(d, monkeypatch, first_post_at=(NOW - timedelta(days=8)).isoformat())
    cfg.api["trial_reels"] = True
    due(d)
    publish.publish_due(d, cfg, NOW)
    assert fake_ig.created[0]["trial"] is False


def test_spam_error_pauses_the_page_and_unschedules_its_clips(d, cfg, fake_ig, monkeypatch):
    setup(d, monkeypatch)
    fake_ig.fail_create = ig.IGError(4, 2207051, "spam")
    ids = due(d, 2)
    publish.publish_due(d, cfg, NOW)
    assert page(d)["paused_at"] and "2207051" in page(d)["pause_reason"]
    for c in ids:
        assert (clip(d, c)["status"], clip(d, c)["scheduled_at"]) == ("approved", None)
    assert d.execute("select count(*) from events where kind='paused'").fetchone()[0] == 1


def test_other_errors_retry_twice_then_fail(d, cfg, fake_ig, monkeypatch):
    setup(d, monkeypatch)
    fake_ig.fail_create = ig.IGError(2, None, "temporary")
    [c] = due(d)
    for i in range(3):
        publish.publish_due(d, cfg, NOW + timedelta(minutes=20 * i))
    row = clip(d, c)
    assert (row["attempts"], row["status"], row["reason"]) == (3, "failed", "temporary")


def test_copyright_match_fails_the_clip_without_pausing(d, cfg, fake_ig, monkeypatch):
    setup(d, monkeypatch)
    cfg.api["copyright_check"] = True
    fake_ig.container = {"status_code": "FINISHED",
                         "copyright_check_status": {"status": "completed", "matches_found": True}}
    [c] = due(d)
    publish.publish_due(d, cfg, NOW)
    assert (clip(d, c)["status"], clip(d, c)["reason"]) == ("failed", "copyright match")
    assert page(d)["paused_at"] is None and fake_ig.published == []


def test_full_quota_waits(d, cfg, fake_ig, monkeypatch):
    setup(d, monkeypatch)
    fake_ig.limit = (50, 50)
    [c] = due(d)
    publish.publish_due(d, cfg, NOW)
    assert fake_ig.created == [] and clip(d, c)["status"] == "scheduled"


def test_paused_page_publishes_nothing(d, cfg, fake_ig, monkeypatch):
    setup(d, monkeypatch)
    [c] = due(d)
    d.execute("update pages set paused_at=? where handle=?", (NOW.isoformat(), P))
    d.commit()
    publish.publish_due(d, cfg, NOW)
    assert fake_ig.created == [] and clip(d, c)["status"] == "scheduled"


def test_expired_token_keeps_clips_and_asks_for_reconnect(d, cfg, fake_ig, monkeypatch):
    setup(d, monkeypatch)
    fake_ig.fail_create = ig.IGError(190, None, "Error validating access token")
    [c] = due(d)
    publish.publish_due(d, cfg, NOW)
    row = clip(d, c)
    assert (row["status"], row["attempts"]) == ("scheduled", 0)
    assert d.execute("select count(*) from events where kind='token_invalid'").fetchone()[0] == 1
    assert page(d)["token_expires_at"] == NOW.isoformat()
    assert d.execute("select count(*) from clips where status='failed'").fetchone()[0] == 0


def test_collaborator_added_for_a_collab_source(d, cfg_with_podcast, fake_ig, monkeypatch):
    cfg = cfg_with_podcast
    cfg.api["collaborators"] = True
    monkeypatch.setattr(store, "url", lambda k, s=3600: "https://example.test/" + k)
    d.execute("update pages set ig_user_id='1', token='tok', token_expires_at=? where handle='podcastbawaal'",
              ((NOW + timedelta(days=50)).isoformat(),))
    d.execute("insert into source_videos (source_id, page, video_id) values ('pod', 'podcastbawaal', 'v1')")
    vid = d.execute("select id from source_videos").fetchone()[0]
    add_clip(d, "podcastbawaal", "scheduled", video_id=vid, scheduled_at=NOW.isoformat())
    publish.publish_due(d, cfg, NOW)
    assert fake_ig.created[0]["collaborators"] == ["podofficial"]


def test_non_https_url_is_refused(d, cfg, fake_ig, monkeypatch):
    setup(d, monkeypatch)
    monkeypatch.setattr(store, "url", lambda k, s=3600: "/files/" + k)
    [c] = due(d)
    publish.publish_due(d, cfg, NOW)
    assert fake_ig.created == [] and clip(d, c)["status"] == "scheduled"


def test_unpause_gives_fresh_slots_not_a_burst(d, cfg, fake_ig, monkeypatch):
    setup(d, monkeypatch)
    for _ in range(2):
        add_clip(d, P, "approved")
    publish.schedule_approved(d, cfg, NOW)
    assert d.execute("select count(*) from clips where status='scheduled'").fetchone()[0] == 2
    accounts.pause(d, P, "test", NOW)
    later = NOW + timedelta(days=5)
    accounts.unpause(d, P, later)
    publish.schedule_approved(d, cfg, later)
    times = sorted(datetime.fromisoformat(r[0]) for r in
                   d.execute("select scheduled_at from clips where status='scheduled'"))
    assert len(times) == 2 and all(t > later for t in times)
    assert times[1] - times[0] >= timedelta(hours=3)
    publish.publish_due(d, cfg, later)
    assert fake_ig.published == []


def test_permalink_failure_never_publishes_twice(d, cfg, fake_ig, monkeypatch):
    setup(d, monkeypatch)
    [c] = due(d)

    def boom(m, t):
        raise ig.IGError(2, None, "temporary")
    monkeypatch.setattr(ig, "media", boom)
    publish.publish_due(d, cfg, NOW)
    publish.publish_due(d, cfg, NOW + timedelta(minutes=20))
    row = clip(d, c)
    assert (row["status"], row["media_id"]) == ("published", "m1") and fake_ig.published == ["c1"]
    assert d.execute("select count(*) from events where kind='permalink_failed'").fetchone()[0] == 1


def test_reconnect_after_expired_token_reslots_instead_of_bursting(d, cfg, fake_ig, monkeypatch):
    setup(d, monkeypatch)
    fake_ig.fail_create = ig.IGError(190, None, "Error validating access token")
    due(d, 2)
    publish.publish_due(d, cfg, NOW)
    fake_ig.fail_create = None
    later = NOW + timedelta(days=3)
    d.execute("update pages set token_expires_at=? where handle=?", ((later + timedelta(days=50)).isoformat(), P))
    d.commit()
    publish.publish_due(d, cfg, later)
    assert fake_ig.published == []
    times = sorted(datetime.fromisoformat(r[0]) for r in d.execute("select scheduled_at from clips"))
    assert len(times) == 2 and all(t > later for t in times)
    assert times[1] - times[0] >= timedelta(hours=3)


def test_two_clips_due_at_once_publish_one_per_tick(d, cfg, fake_ig, monkeypatch):
    setup(d, monkeypatch)
    due(d, 2)
    publish.publish_due(d, cfg, NOW)
    assert len(fake_ig.published) == 1
