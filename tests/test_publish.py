from datetime import UTC, datetime, timedelta

from helpers import add_clip

from pages import accounts, ig, publish, store
from pages import db as dbm

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
    add_clip(d, "podcastbawaal", "scheduled", video_id="v1", scheduled_at=NOW.isoformat())  # the YouTube id
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


def test_timeout_after_instagram_posted_never_posts_twice(d, cfg, fake_ig, monkeypatch):
    setup(d, monkeypatch)
    [c] = due(d)
    real = fake_ig.publish

    def posted_then_timeout(uid, token, cid):
        real(uid, token, cid)
        fake_ig.container = {"status_code": "PUBLISHED"}
        raise TimeoutError("read timed out")
    monkeypatch.setattr(ig, "publish", posted_then_timeout)
    publish.publish_due(d, cfg, NOW)
    monkeypatch.setattr(ig, "publish", real)
    publish.publish_due(d, cfg, NOW + timedelta(minutes=20))
    row = clip(d, c)
    assert len(fake_ig.created) == 1 and fake_ig.published == ["c1"]
    assert (row["status"], row["container_id"]) == ("published", "c1") and row["published_at"]
    assert d.execute("select count(*) from events where kind='published_without_id'").fetchone()[0] == 1


def test_a_clip_another_runner_is_publishing_is_left_alone(d, cfg, fake_ig, monkeypatch):
    setup(d, monkeypatch)
    [c] = due(d)
    d.execute("update clips set status='publishing', claimed_at=? where id=?", (datetime.now(UTC).isoformat(), c))
    d.commit()
    publish.publish_due(d, cfg, NOW + timedelta(minutes=5))
    assert fake_ig.created == [] and fake_ig.published == []


def stuck(d, c, **cols):
    sets = ", ".join(f"{k}=?" for k in cols)
    d.execute(f"update clips set status='publishing', claimed_at=?{', ' + sets if sets else ''} where id=?",
              ((datetime.now(UTC) - timedelta(minutes=20)).isoformat(), *cols.values(), c))
    d.commit()


def test_a_stuck_publishing_clip_is_resolved_through_its_container(d, cfg, fake_ig, monkeypatch):
    setup(d, monkeypatch)
    [c] = due(d)
    stuck(d, c, container_id="c9")
    publish.publish_due(d, cfg, NOW + timedelta(minutes=20))
    assert fake_ig.created == [] and fake_ig.published == ["c9"] and clip(d, c)["status"] == "published"


def test_claim_taken_after_the_due_query_is_not_stolen(d, cfg_with_podcast, fake_ig, monkeypatch):
    """Runner B listed X as scheduled; runner A claims X while B works on Y; B then re-reads X."""
    setup(d, monkeypatch)
    d.execute("update pages set ig_user_id='1', token='tok', token_expires_at=? where handle='podcastbawaal'",
              ((NOW + timedelta(days=50)).isoformat(),))
    d.commit()
    add_clip(d, "podcastbawaal", "scheduled", kind="script", scheduled_at=(NOW - timedelta(minutes=2)).isoformat())
    x = add_clip(d, P, "scheduled", kind="script", scheduled_at=(NOW - timedelta(minutes=1)).isoformat())
    real = fake_ig.create_reel

    def create(*a, **k):
        if not fake_ig.created:  # runner A's claim on X
            d.execute("update clips set status='publishing', claimed_at=? where id=?", (datetime.now(UTC).isoformat(), x))
            d.commit()
        return real(*a, **k)
    monkeypatch.setattr(ig, "create_reel", create)
    publish.publish_due(d, cfg_with_podcast, NOW)
    assert len(fake_ig.created) == 1 and fake_ig.published == ["c1"]


def test_an_in_progress_container_is_waited_on_not_replaced(d, cfg, fake_ig, monkeypatch):
    setup(d, monkeypatch)
    [c] = due(d)
    d.execute("update clips set container_id='c9' where id=?", (c,))
    d.commit()
    fake_ig.container = {"status_code": "IN_PROGRESS"}
    publish.publish_due(d, cfg, NOW)
    assert fake_ig.created == [] and fake_ig.published == ["c9"]


def test_full_quota_late_at_night_reslots_instead_of_posting_outside_the_window(d, cfg, fake_ig, monkeypatch):
    setup(d, monkeypatch)
    slot = datetime(2026, 11, 2, 17, tzinfo=UTC)  # 22:30 IST
    c = add_clip(d, P, "scheduled", kind="script", scheduled_at=slot.isoformat())
    fake_ig.limit = (50, 50)
    t = slot
    while t <= datetime(2026, 11, 2, 20, 30, tzinfo=UTC):  # until 02:00 IST
        publish.publish_due(d, cfg, t)
        t += timedelta(minutes=5)
    fake_ig.limit = (0, 50)
    publish.publish_due(d, cfg, t)
    row = clip(d, c)
    assert row["status"] == "scheduled" and fake_ig.published == []
    assert datetime.fromisoformat(row["scheduled_at"]) > t


def test_a_published_container_wins_over_lateness_and_a_withdrawn_source(d, cfg, fake_ig, monkeypatch):
    setup(d, monkeypatch)
    d.execute("insert into source_videos (source_id, page, video_id) values ('gone', 'billikalesh', 'v8')")
    c = add_clip(d, P, "scheduled", video_id="v8", container_id="c9",
                 scheduled_at=(NOW - timedelta(hours=5)).isoformat())
    fake_ig.container = {"status_code": "PUBLISHED"}
    publish.publish_due(d, cfg, NOW)
    assert clip(d, c)["status"] == "published" and fake_ig.created == []


def test_a_stuck_clip_without_a_live_container_follows_the_time_rules(d, cfg, fake_ig, monkeypatch):
    setup(d, monkeypatch)
    c = add_clip(d, P, "scheduled", kind="script", scheduled_at=(NOW - timedelta(hours=5)).isoformat())
    stuck(d, c)
    publish.publish_due(d, cfg, NOW)
    row = clip(d, c)
    assert fake_ig.created == [] and row["status"] == "scheduled" and row["claimed_at"] is None
    assert datetime.fromisoformat(row["scheduled_at"]) > NOW


def test_pause_moves_publishing_clips_back_to_approved(d, cfg, fake_ig, monkeypatch):
    setup(d, monkeypatch)
    [c] = due(d)
    stuck(d, c)
    accounts.pause(d, P, "test", NOW)
    row = clip(d, c)
    assert (row["status"], row["scheduled_at"], row["claimed_at"]) == ("approved", None, None)


def test_an_unexpected_error_on_one_clip_does_not_stop_the_next_page(d, cfg_with_podcast, fake_ig, monkeypatch):
    setup(d, monkeypatch)
    d.execute("update pages set ig_user_id='1', token='tok', token_expires_at=? where handle='podcastbawaal'",
              ((NOW + timedelta(days=50)).isoformat(),))
    d.execute("insert into pages (handle, token, ig_user_id, token_expires_at) values ('gone', 'tok', '2', ?)",
              ((NOW + timedelta(days=50)).isoformat(),))
    d.commit()
    add_clip(d, "gone", "scheduled", scheduled_at=(NOW - timedelta(hours=3)).isoformat())  # late: _reslot KeyErrors
    other = add_clip(d, "podcastbawaal", "scheduled", kind="script",
                     scheduled_at=(NOW - timedelta(minutes=1)).isoformat())
    publish.publish_due(d, cfg_with_podcast, NOW)
    assert clip(d, other)["status"] == "published"
    assert d.execute("select count(*) from events where kind='publish_error'").fetchone()[0] == 1


def test_a_clip_whose_source_was_withdrawn_is_not_published(d, cfg, fake_ig, monkeypatch):
    setup(d, monkeypatch)
    d.execute("insert into source_videos (source_id, page, video_id) values ('gone', 'billikalesh', 'v7')")
    c = add_clip(d, P, "scheduled", video_id="v7", scheduled_at=(NOW - timedelta(minutes=1)).isoformat())
    publish.publish_due(d, cfg, NOW)
    assert fake_ig.created == []
    assert (clip(d, c)["status"], clip(d, c)["reason"]) == ("failed", "source no longer permitted")
    assert d.execute("select count(*) from events where kind='source_withdrawn'").fetchone()[0] == 1


class Clock:
    t = datetime.now(UTC)


class FakeDT(datetime):
    @classmethod
    def now(cls, tz=None):
        return Clock.t


def test_a_claim_late_in_a_long_tick_is_not_born_stale(tmp_path, cfg_with_podcast, fake_ig, monkeypatch):
    """Runner 1 spends 16 min on Y, then claims X; runner 2 ticks while runner 1 creates X's container."""
    monkeypatch.setattr(publish, "datetime", FakeDT)
    monkeypatch.setattr(Clock, "t", datetime.now(UTC))
    monkeypatch.setattr(store, "url", lambda k, s=3600: "https://example.test/" + k)
    path = tmp_path / "t.db"
    d1 = dbm.connect(path)
    dbm.add_pages(d1, cfg_with_podcast)
    for h in ("billikalesh", "podcastbawaal"):
        d1.execute("update pages set ig_user_id='1', token='tok', token_expires_at=? where handle=?",
                   ((NOW + timedelta(days=50)).isoformat(), h))
    d1.commit()
    add_clip(d1, "podcastbawaal", "scheduled", kind="script", scheduled_at=(NOW - timedelta(minutes=2)).isoformat())
    add_clip(d1, P, "scheduled", kind="script", scheduled_at=(NOW - timedelta(minutes=1)).isoformat())
    real_wait, real_create = fake_ig.wait_container, fake_ig.create_reel
    n = []

    def wait(cid, token, **k):
        if cid == "c1":
            Clock.t += timedelta(minutes=16)
        return real_wait(cid, token, **k)

    def create(*a, **k):
        n.append(1)
        if len(n) == 2:
            publish.publish_due(dbm.connect(path), cfg_with_podcast, NOW + timedelta(minutes=16))
        return real_create(*a, **k)
    monkeypatch.setattr(ig, "wait_container", wait)
    monkeypatch.setattr(ig, "create_reel", create)
    publish.publish_due(d1, cfg_with_podcast, NOW)
    assert len(fake_ig.created) == 2 and len(fake_ig.published) == 2


def test_a_claim_landing_after_the_re_read_wins(d, cfg, fake_ig, monkeypatch):
    setup(d, monkeypatch)
    [c] = due(d)
    real = publish._live_pages

    def other_runner_claims(db, now):  # runs between the re-read and the claim update
        db.execute("update clips set status='publishing', claimed_at=? where id=?", (datetime.now(UTC).isoformat(), c))
        db.commit()
        return real(db, now)
    monkeypatch.setattr(publish, "_live_pages", other_runner_claims)
    publish.publish_due(d, cfg, NOW)
    assert fake_ig.created == [] and fake_ig.published == []


def test_the_window_is_a_hard_limit(d, cfg, fake_ig, monkeypatch):
    setup(d, monkeypatch)
    slot = datetime(2026, 11, 2, 17, tzinfo=UTC)  # 22:30 IST
    c = add_clip(d, P, "scheduled", kind="script", scheduled_at=slot.isoformat())
    fake_ig.limit = (50, 50)
    publish.publish_due(d, cfg, slot)
    fake_ig.limit = (0, 50)
    publish.publish_due(d, cfg, slot + timedelta(minutes=45))  # 23:15 IST: quota free, window shut
    row = clip(d, c)
    assert fake_ig.published == [] and row["status"] == "scheduled"
    assert datetime.fromisoformat(row["scheduled_at"]) > slot + timedelta(minutes=45)
    assert d.execute("select count(*) from events where kind='rescheduled'").fetchone()[0] == 1
