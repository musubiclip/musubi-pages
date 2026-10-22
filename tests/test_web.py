import json
import sys
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient
from helpers import add_clip

from pages import db, ig, web


@pytest.fixture
def client(d, cfg_with_podcast, local_store, monkeypatch):
    monkeypatch.delenv("CF_ACCESS_AUD", raising=False)
    path = d.execute("pragma database_list").fetchone()[2]

    async def test_db():  # async, like get_db: sqlite connections stay on the loop thread
        conn = db.connect(path)
        yield conn
        conn.close()

    web.app.dependency_overrides[web.get_db] = test_db
    web.app.dependency_overrides[web.get_cfg] = lambda: cfg_with_podcast
    yield TestClient(web.app)
    web.app.dependency_overrides.clear()


def add_draft(d, **cols):
    d.execute("insert into source_videos (source_id, page, video_id, status) values ('pod', 'podcastbawaal', 'v1', 'done')")
    return add_clip(d, "podcastbawaal", "draft", video_id="v1",
                    moment=json.dumps({"hook_text": "Ninety percent fail here"}),
                    layer=json.dumps({"intro": "Listen up", "takeaway": "So start small",
                                      "cards": [{"at": 1, "title": "Fact", "body": "Card body"}],
                                      "flags": ["health claim"]}),
                    credits=json.dumps(["Clip: Pod Host"]), caption="My <b>caption</b>", **cols)


def status(d, cid):
    return d.execute("select status, caption, reason from clips where id = ?", (cid,)).fetchone()


def state(client):
    r = client.get("/api/state")
    assert r.status_code == 200
    return r.json()


def page(client, handle):
    return next(p for p in state(client)["pages"] if p["handle"] == handle)


def test_state_shows_a_draft_with_its_permission_and_flags(client, d):
    cid = add_draft(d)
    [c] = state(client)["drafts"]
    assert (c["id"], c["page"], c["kind"]) == (cid, "podcastbawaal", "clip")
    assert c["hook"] == "Ninety percent fail here"
    assert c["video_url"] == f"/files/clips/{cid}.mp4"
    assert c["layer"] == {"intro": "Listen up", "takeaway": "So start small",
                          "cards": [{"at": 1, "title": "Fact", "body": "Card body"}]}
    assert c["flags"] == ["health claim"] and c["claims"] == []
    assert c["credits"] == [{"text": "Clip: Pod Host", "url": None}]
    assert c["caption"] == "My <b>caption</b>"  # raw: the app escapes it when it renders
    assert c["source"]["name"] == "pod" and "Pod Host" in c["source"]["permission"]
    assert c["source"]["proof"] == "https://drive.google.com/x"
    assert c["source"]["instagram"] == "https://www.instagram.com/podofficial/"
    assert c["note"] is None and c["created_at"]


def test_one_off_video_shows_its_note(client, d):
    d.execute("insert into source_videos (source_id, page, video_id, note) values (null, 'podcastbawaal', 'v2', "
              "'guest sent it on email')")
    add_clip(d, "podcastbawaal", "draft", video_id="v2")
    [c] = state(client)["drafts"]
    assert c["note"] == "guest sent it on email" and c["source"] is None


def test_script_draft_shows_claims_and_credit_links(client, d):
    add_clip(d, "tech_bawaal", "draft", kind="script",
             script=json.dumps({"hook_text": "Cats see in the dark", "claims": ["Cats see in low light"],
                                "flags": []}),
             credits=json.dumps([{"credit": "Footage: Ann / pexels", "page_url": "https://pexels.com/v"}]))
    [c] = state(client)["drafts"]
    assert c["hook"] == "Cats see in the dark" and c["claims"] == ["Cats see in low light"]
    assert c["credits"] == [{"text": "Footage: Ann / pexels", "url": "https://pexels.com/v"}]
    assert c["layer"] is None


def test_state_shape(client, d):
    add_clip(d, "podcastbawaal", "approved")
    add_clip(d, "podcastbawaal", "scheduled")
    add_clip(d, "podcastbawaal", "published")
    add_draft(d)
    s = state(client)
    assert [p["handle"] for p in s["pages"]] == ["podcastbawaal", "tech_bawaal"]
    p = s["pages"][0]
    assert set(p) >= {"handle", "pipeline", "connected", "reconnect", "token_expires_at", "paused", "pause_reason",
                      "status_due", "recommendable", "status_checked_at", "metrics", "counts", "settings"}
    assert p["pipeline"] == "clips" and s["pages"][1]["pipeline"] == "clips"
    assert p["counts"] == {"draft": 1, "approved": 1, "scheduled": 1, "published": 1}
    assert p["metrics"] == {"reels": 0, "median_views": None, "non_follower_share": None}
    assert sorted(r["status"] for r in p["reels"]) == ["approved", "published", "scheduled"]
    assert set(p["reels"][0]) >= {"id", "kind", "hook", "video_url", "cover_url", "scheduled_at", "permalink"}
    assert p["settings"]["window"] == [9, 23] and p["settings"]["daily_target"] == 1
    assert p["settings"]["voice"] and p["settings"]["theme"]["hot"]
    assert p["connected"] is False and p["reconnect"] is True and p["paused"] is False
    assert p["recommendable"] is None and p["status_due"] is True
    assert s["problems"] == []


def test_approve_saves_the_edited_caption(client, d):
    cid = add_draft(d)
    r = client.post(f"/api/clips/{cid}/approve", json={"caption": "edited"})
    assert r.status_code == 200
    assert tuple(status(d, cid))[:2] == ("approved", "edited")
    r = client.post(f"/api/clips/{cid}/approve", json={"caption": "again"})
    assert r.status_code == 409 and r.json()["detail"] == "clip is not a draft"


def test_approve_refuses_a_long_caption(client, d):
    cid = add_draft(d)
    r = client.post(f"/api/clips/{cid}/approve", json={"caption": "x" * 2201})
    assert r.status_code == 400 and "2200" in r.json()["detail"]
    assert status(d, cid)["status"] == "draft"


def test_reject_needs_a_reason(client, d):
    cid = add_draft(d)
    assert client.post(f"/api/clips/{cid}/reject", json={"reason": ""}).status_code == 400
    assert client.post(f"/api/clips/{cid}/reject", json={"reason": "  "}).status_code == 400
    assert client.post(f"/api/clips/{cid}/reject", json={"reason": "off topic "}).status_code == 200
    assert tuple(status(d, cid))[::2] == ("rejected", "off topic")
    sid = add_clip(d, "podcastbawaal", "scheduled")
    assert client.post(f"/api/clips/{sid}/reject", json={"reason": "late"}).status_code == 409
    assert status(d, sid)["status"] == "scheduled"


@pytest.mark.parametrize("days, warned", [(9, True), (11, False)])
def test_token_warning_ten_days_before_expiry(client, d, days, warned):
    expires = (datetime.now(UTC) + timedelta(days=days)).isoformat()
    d.execute("update pages set token = 't', token_expires_at = ?", (expires,))
    d.commit()
    p = page(client, "podcastbawaal")
    assert p["reconnect"] is warned and p["connected"] is True and p["token_expires_at"] == expires


def test_not_recommendable_pauses_the_page(client, d):
    r = client.post("/api/pages/podcastbawaal/status", json={"recommendable": False})
    assert r.status_code == 200
    p = d.execute("select * from pages where handle = 'podcastbawaal'").fetchone()
    assert p["paused_at"] and p["pause_reason"] == "not recommendable"
    assert p["recommendable"] == "no" and p["status_checked_at"]
    p = page(client, "podcastbawaal")
    assert p["paused"] is True and p["pause_reason"] == "not recommendable" and p["recommendable"] is False


def test_status_must_be_yes_or_no(client, d):
    r = client.post("/api/pages/podcastbawaal/status", json={"recommendable": "maybe"})
    assert r.status_code == 400 and "recommendable" in r.json()["detail"]
    assert d.execute("select status_checked_at from pages where handle = 'podcastbawaal'").fetchone()[0] is None


def test_account_status_reminder_after_seven_days(client, d):
    d.execute("update pages set status_checked_at = ?", ((datetime.now(UTC) - timedelta(days=8)).isoformat(),))
    d.commit()
    assert all(p["status_due"] for p in state(client)["pages"])
    client.post("/api/pages/podcastbawaal/status", json={"recommendable": True})
    client.post("/api/pages/tech_bawaal/status", json={"recommendable": True})
    pages = state(client)["pages"]
    assert not any(p["status_due"] for p in pages) and all(p["recommendable"] is True for p in pages)
    assert not any(p["paused"] for p in pages)


def test_unpause(client, d):
    d.execute("update pages set paused_at = 'x', pause_reason = 'boom'")
    d.commit()
    assert client.post("/api/pages/podcastbawaal/unpause").status_code == 200
    assert d.execute("select paused_at from pages where handle = 'podcastbawaal'").fetchone()[0] is None


def test_links_calls_add_link(client, monkeypatch):
    calls = []

    def fake(db, cfg, url, page, note):
        if "bad" in url:
            raise ValueError("not an allowed source")
        calls.append((url, page, note))

    monkeypatch.setitem(sys.modules, "pages.clips_pipeline", SimpleNamespace(add_link=fake))
    r = client.post("/api/links", json={"url": "https://y/1", "page": "podcastbawaal", "note": ""})
    assert r.status_code == 200 and calls == [("https://y/1", "podcastbawaal", "")]
    r = client.post("/api/links", json={"url": "https://y/bad", "page": "podcastbawaal"})
    assert r.status_code == 400 and r.json()["detail"] == "not an allowed source"


def test_links_go_only_to_clip_pages(client, d, cfg_with_podcast):
    cfg_with_podcast.pages["tech_bawaal"].pipeline = "script"  # a non clip page
    r = client.post("/api/links", json={"url": "https://www.youtube.com/watch?v=abcdefghijk", "page": "tech_bawaal"})
    assert r.status_code == 400 and "clip pages" in r.json()["detail"]
    assert d.execute("select count(*) from source_videos").fetchone()[0] == 0


def test_connect_stores_the_token_and_never_shows_it(client, d, monkeypatch):
    secret = "IGAAsecret-token-123"
    monkeypatch.setattr(ig, "me", lambda t: {"user_id": "1789", "username": "tech_bawaal"})
    r = client.post("/api/pages/tech_bawaal/connect", json={"token": secret})
    assert r.status_code == 200 and secret not in r.text
    assert d.execute("select token from pages where handle = 'tech_bawaal'").fetchone()[0] == secret
    s = client.get("/api/state")
    assert secret not in s.text and "IGAA" not in s.text
    assert next(p for p in s.json()["pages"] if p["handle"] == "tech_bawaal")["connected"] is True


def test_connect_refuses_a_token_for_another_account(client, d, monkeypatch):
    secret = "IGAAother-token-456"
    monkeypatch.setattr(ig, "me", lambda t: {"user_id": "5", "username": "musubi_clip"})
    r = client.post("/api/pages/tech_bawaal/connect", json={"token": secret})
    assert r.status_code == 400 and r.json()["detail"] == "token is for @musubi_clip, not @tech_bawaal"
    assert secret not in r.text
    assert d.execute("select token from pages where handle = 'tech_bawaal'").fetchone()[0] is None


def test_connect_errors_never_echo_the_token(client, monkeypatch):
    secret = "IGAAbroken-token-789"

    def bad(t):
        raise ig.IGError(190, None, f"Cannot parse access token {t}")
    monkeypatch.setattr(ig, "me", bad)
    r = client.post("/api/pages/tech_bawaal/connect", json={"token": secret})
    assert r.status_code == 400 and secret not in r.text and "Cannot parse" in r.text
    r = client.post("/api/pages/tech_bawaal/connect", json={"token": 12345})  # bad body: no input in the error
    assert r.status_code == 400 and "12345" not in r.text


def test_files_served_only_inside_a_local_store(client, local_store, monkeypatch):
    (local_store / "clips").mkdir(parents=True)
    (local_store / "clips" / "1.mp4").write_bytes(b"vid")
    assert client.get("/files/clips/1.mp4").content == b"vid"
    assert client.get("/files/clips/2.mp4").status_code == 404
    assert client.get("/files/..%2F..%2Ft.db").status_code == 404
    assert client.get("/files/%2E%2E/t.db").status_code == 404
    monkeypatch.setenv("PAGES_STORE", "s3://bucket")
    assert client.get("/files/clips/1.mp4").status_code == 503  # no Access configured: nothing is served


def test_files_never_serves_backups(client, local_store):
    (local_store / "backups").mkdir(parents=True)
    (local_store / "backups" / "pages-2026-11-02.db").write_bytes(b"db")
    (local_store / "clips").mkdir(parents=True)
    (local_store / "clips" / "1.mp4").write_bytes(b"vid")
    assert client.get("/files/backups/pages-2026-11-02.db").status_code == 404
    assert client.get("/files/clips/1.mp4").status_code == 200


@pytest.mark.parametrize("path", ["/files/clips/%2E%2E/backups/pages-2026-11-02.db",
                                  "/files/clips/..%2Fbackups%2Fpages-2026-11-02.db",
                                  "/files/clips%2F..%2Fbackups%2Fpages-2026-11-02.db"])
def test_files_cannot_climb_out_of_clips(client, local_store, path):
    (local_store / "backups").mkdir(parents=True)
    (local_store / "backups" / "pages-2026-11-02.db").write_bytes(b"db")
    (local_store / "clips").mkdir(parents=True)
    assert client.get(path).status_code == 404


def test_withdrawn_sources_show_as_problems(client, d):
    db.event(d, "podcastbawaal", "source_withdrawn", "clip 7")
    [p] = state(client)["problems"]
    assert (p["page"], p["kind"], p["detail"], p["count"]) == ("podcastbawaal", "source_withdrawn", "clip 7", 1)


def test_state_lists_problems_from_the_last_week(client, d):
    add_clip(d, "podcastbawaal", "failed", reason="layer too long")
    d.execute("insert into source_videos (page, video_id, url, status, note, created_at) values "
              "('podcastbawaal', 'v9', 'https://www.youtube.com/watch?v=v9', 'skipped', 'not an allowed source', ?)",
              (datetime.now(UTC).isoformat(),))
    add_clip(d, "podcastbawaal", "failed", reason="ancient", created_at=(datetime.now(UTC) - timedelta(days=8)).isoformat())
    d.commit()
    db.event(d, "tech_bawaal", "insights_failed", "boom 42")
    db.event(d, "tech_bawaal", "insights_failed", "boom 42")
    db.event(d, "tech_bawaal", "connected", "fine")
    problems = state(client)["problems"]
    text = json.dumps(problems)
    assert "layer too long" in text and "not an allowed source" in text and "ancient" not in text
    assert text.count("boom 42") == 1 and "connected" not in text
    assert next(p for p in problems if p["detail"] == "boom 42")["count"] == 2
    assert [p["at"] for p in problems] == sorted((p["at"] for p in problems), reverse=True)


def test_state_works_before_init(client, d):
    d.execute("delete from pages")
    d.commit()
    assert len(state(client)["pages"]) == 2


def test_deployed_store_without_access_is_closed(client, monkeypatch):
    monkeypatch.setenv("PAGES_STORE", "s3://bucket")
    r = client.get("/api/state")
    assert r.status_code == 503 and "Access not configured" in r.text
    assert client.get("/").status_code == 503


def test_cross_site_posts_are_refused(client, d):
    cid = add_draft(d)
    r = client.post(f"/api/clips/{cid}/reject", json={"reason": "x"}, headers={"Origin": "https://evil.example"})
    assert r.status_code == 403 and status(d, cid)["status"] == "draft"
    r = client.post(f"/api/clips/{cid}/reject", json={"reason": "x"}, headers={"Origin": "http://testserver"})
    assert r.status_code == 200


@pytest.mark.parametrize("caption", ["", "   ", "a #b #c #d #e #f #g"])
def test_approve_refuses_empty_or_hashtag_heavy_captions(client, d, caption):
    cid = add_draft(d)
    assert client.post(f"/api/clips/{cid}/approve", json={"caption": caption}).status_code == 400


def test_approve_refuses_a_caption_that_drops_a_credit(client, d):
    cid = add_draft(d)
    d.execute("update clips set caption = ? where id = ?", ("Burnout.\n\n🎙️ Video v1 via @podofficial", cid))
    sid = add_clip(d, "tech_bawaal", "draft", kind="script", caption="Cats.\n\nFootage: Ann / pexels",
                   credits=json.dumps([{"credit": "Footage: Ann / pexels", "page_url": "https://pexels.com/v"}]))
    d.commit()
    r = client.post(f"/api/clips/{cid}/approve", json={"caption": "Burnout."})
    assert r.status_code == 400 and "credit" in r.json()["detail"]
    assert client.post(f"/api/clips/{sid}/approve", json={"caption": "Cats."}).status_code == 400
    ok = client.post(f"/api/clips/{sid}/approve", json={"caption": "Cats!\n\nFootage: Ann / pexels"})
    assert ok.status_code == 200


def test_old_form_routes_are_gone(client, d):
    cid = add_draft(d)
    assert client.post(f"/clips/{cid}/approve", data={"caption": "x"}).status_code in (404, 405)
    assert status(d, cid)["status"] == "draft"


def test_home_answers_without_a_build(client, monkeypatch):
    r = client.get("/")
    assert r.status_code == 200  # the built app, or the hint to build it


def test_access_required_when_configured(client, monkeypatch):
    monkeypatch.setenv("CF_ACCESS_AUD", "aud")
    monkeypatch.setenv("CF_ACCESS_TEAM", "musubi.cloudflareaccess.com")
    assert client.get("/api/state").status_code == 403
    assert client.get("/").status_code == 403


def test_access_allows_only_musubiclip_emails(client, monkeypatch):
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)

    class FakeJWKs:
        def __init__(self, url):
            assert url == "https://musubi.cloudflareaccess.com/cdn-cgi/access/certs"

        def get_signing_key_from_jwt(self, token):
            return SimpleNamespace(key=key.public_key())

    monkeypatch.setattr(web.jwt, "PyJWKClient", FakeJWKs)
    web._jwks.clear()
    monkeypatch.setenv("CF_ACCESS_AUD", "aud")
    monkeypatch.setenv("CF_ACCESS_TEAM", "musubi.cloudflareaccess.com")

    def get(email, aud="aud", exp=True):
        claims = {"email": email, "aud": aud}
        if exp:
            claims["exp"] = datetime.now(UTC) + timedelta(minutes=5)
        token = jwt.encode(claims, key, algorithm="RS256")
        return client.get("/api/state", headers={"Cf-Access-Jwt-Assertion": token}).status_code

    assert get("a@gmail.com") == 403
    assert get("a@musubiclip.com.evil.com") == 403
    assert get("prateek@musubiclip.com", aud="other") == 403
    assert get("prateek@musubiclip.com", exp=False) == 403
    assert get("Prateek@MusubiClip.com") == 200


def test_state_gives_a_draft_its_cover(client, d):
    cid = add_draft(d)
    assert state(client)["drafts"][0]["cover_url"] is None
    d.execute("update clips set cover_key = ? where id = ?", (f"clips/{cid}.jpg", cid))
    d.commit()
    assert state(client)["drafts"][0]["cover_url"] == f"/files/clips/{cid}.jpg"


def test_unschedule_and_reschedule(client, d):
    from datetime import UTC, datetime, timedelta
    from pages.schedule import IST
    sid = add_clip(d, "podcastbawaal", "scheduled", scheduled_at="2030-01-01T05:00:00+00:00")
    noon = (datetime.now(IST) + timedelta(days=2)).replace(hour=12, minute=30, second=0, microsecond=0)
    assert client.post(f"/api/clips/{sid}/reschedule", json={"at": noon.isoformat()}).status_code == 200
    assert d.execute("select scheduled_at from clips where id = ?", (sid,)).fetchone()[0] == noon.astimezone(UTC).isoformat()
    assert client.post(f"/api/clips/{sid}/reschedule", json={"at": noon.replace(hour=3).isoformat()}).status_code == 400
    assert client.post(f"/api/clips/{sid}/reschedule", json={"at": "2020-01-01T12:00:00+05:30"}).status_code == 400
    assert client.post(f"/api/clips/{sid}/unschedule").status_code == 200
    assert status(d, sid)["status"] == "rejected"
    assert client.post(f"/api/clips/{sid}/unschedule").status_code == 409
    assert client.post(f"/api/clips/{sid}/reschedule", json={"at": noon.isoformat()}).status_code == 409
