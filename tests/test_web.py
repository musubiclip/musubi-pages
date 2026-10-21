import json
import sys
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient
from helpers import add_clip

from pages import db, web


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


def test_review_shows_a_draft_with_its_permission_and_flags(client, d):
    add_draft(d)
    r = client.get("/")
    assert r.status_code == 200
    for text in ("Ninety percent fail here", "Listen up", "Card body", "health claim", "Pod Host",
                 "https://www.instagram.com/podofficial/", "/files/clips/1.mp4", "Clip: Pod Host"):
        assert text in r.text
    assert "My &lt;b&gt;caption&lt;/b&gt;" in r.text


def test_one_off_video_shows_its_note(client, d):
    d.execute("insert into source_videos (source_id, page, video_id, note) values (null, 'podcastbawaal', 'v2', "
              "'guest sent it on email')")
    add_clip(d, "podcastbawaal", "draft", video_id="v2")
    assert "guest sent it on email" in client.get("/").text


def test_approve_saves_the_edited_caption(client, d):
    cid = add_draft(d)
    r = client.post(f"/clips/{cid}/approve", data={"caption": "edited"}, follow_redirects=False)
    assert r.status_code == 303
    assert tuple(status(d, cid))[:2] == ("approved", "edited")
    assert client.post(f"/clips/{cid}/approve", data={"caption": "again"}).status_code == 409


def test_approve_refuses_a_long_caption(client, d):
    cid = add_draft(d)
    assert client.post(f"/clips/{cid}/approve", data={"caption": "x" * 2201}).status_code == 400
    assert status(d, cid)["status"] == "draft"


def test_reject_needs_a_reason(client, d):
    cid = add_draft(d)
    assert client.post(f"/clips/{cid}/reject", data={"reason": ""}).status_code == 400
    assert client.post(f"/clips/{cid}/reject", data={"reason": "off topic"}, follow_redirects=False).status_code == 303
    assert tuple(status(d, cid))[::2] == ("rejected", "off topic")
    sid = add_clip(d, "podcastbawaal", "scheduled")
    assert client.post(f"/clips/{sid}/reject", data={"reason": "late"}).status_code == 409
    assert status(d, sid)["status"] == "scheduled"


@pytest.mark.parametrize("days, warned", [(9, True), (11, False)])
def test_token_warning_ten_days_before_expiry(client, d, days, warned):
    d.execute("update pages set token = 't', token_expires_at = ?",
              ((datetime.now(UTC) + timedelta(days=days)).isoformat(),))
    d.commit()
    assert ("reconnect" in client.get("/").text) is warned


def test_not_recommendable_pauses_the_page(client, d):
    r = client.post("/pages/podcastbawaal/status", data={"recommendable": "no"}, follow_redirects=False)
    assert r.status_code == 303
    p = d.execute("select * from pages where handle = 'podcastbawaal'").fetchone()
    assert p["paused_at"] and p["pause_reason"] == "not recommendable"
    assert p["recommendable"] == "no" and p["status_checked_at"]
    assert "not recommendable" in client.get("/").text


def test_account_status_reminder_after_seven_days(client, d):
    d.execute("update pages set status_checked_at = ?", ((datetime.now(UTC) - timedelta(days=8)).isoformat(),))
    d.commit()
    assert "check Account Status" in client.get("/").text
    client.post("/pages/podcastbawaal/status", data={"recommendable": "yes"})
    client.post("/pages/billikalesh/status", data={"recommendable": "yes"})
    assert "check Account Status" not in client.get("/").text


def test_unpause(client, d):
    d.execute("update pages set paused_at = 'x', pause_reason = 'boom'")
    d.commit()
    assert client.post("/pages/podcastbawaal/unpause", follow_redirects=False).status_code == 303
    assert d.execute("select paused_at from pages where handle = 'podcastbawaal'").fetchone()[0] is None


def test_links_calls_add_link(client, monkeypatch):
    calls = []

    def fake(db, cfg, url, page, note):
        if "bad" in url:
            raise ValueError("not an allowed source")
        calls.append((url, page, note))

    monkeypatch.setitem(sys.modules, "pages.clips_pipeline", SimpleNamespace(add_link=fake))
    r = client.post("/links", data={"url": "https://y/1", "page": "podcastbawaal", "note": ""}, follow_redirects=False)
    assert r.status_code == 303 and calls == [("https://y/1", "podcastbawaal", "")]
    r = client.post("/links", data={"url": "https://y/bad", "page": "podcastbawaal", "note": ""})
    assert r.status_code == 400 and "not an allowed source" in r.text


def test_files_served_only_inside_a_local_store(client, local_store, monkeypatch):
    (local_store / "clips").mkdir(parents=True)
    (local_store / "clips" / "1.mp4").write_bytes(b"vid")
    assert client.get("/files/clips/1.mp4").content == b"vid"
    assert client.get("/files/clips/2.mp4").status_code == 404
    assert client.get("/files/..%2F..%2Ft.db").status_code == 404
    assert client.get("/files/%2E%2E/t.db").status_code == 404
    monkeypatch.setenv("PAGES_STORE", "s3://bucket")
    assert client.get("/files/clips/1.mp4").status_code == 404


def test_access_required_when_configured(client, monkeypatch):
    monkeypatch.setenv("CF_ACCESS_AUD", "aud")
    monkeypatch.setenv("CF_ACCESS_TEAM", "musubi.cloudflareaccess.com")
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
        return client.get("/", headers={"Cf-Access-Jwt-Assertion": token}).status_code

    assert get("a@gmail.com") == 403
    assert get("a@musubiclip.com.evil.com") == 403
    assert get("prateek@musubiclip.com", aud="other") == 403
    assert get("prateek@musubiclip.com", exp=False) == 403
    assert get("Prateek@MusubiClip.com") == 200
