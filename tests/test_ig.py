import io
import json
import urllib.error
import urllib.parse
from datetime import date

import pytest

from pages import ig
from tests.fake_ig import FakeIG


class Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()


def fake_http_error(monkeypatch, status, body):
    def urlopen(req, timeout=None):
        raw = json.dumps(body).encode() if isinstance(body, dict) else body.encode()
        raise urllib.error.HTTPError(req.full_url, status, "err", {}, io.BytesIO(raw))
    monkeypatch.setattr(ig.urllib.request, "urlopen", urlopen)


def fake_responses(monkeypatch, *bodies):
    """Answer each request with the next body (an Exception body is raised). Returns the request log."""
    calls, queue = [], list(bodies)

    def urlopen(req, timeout=None):
        url = urllib.parse.urlparse(req.full_url)
        params = dict(urllib.parse.parse_qsl(url.query))
        if req.data:
            params.update(urllib.parse.parse_qsl(req.data.decode()))
        calls.append((req.get_method(), url.path, params))
        body = queue.pop(0)
        if isinstance(body, Exception):
            raise body
        return Resp(json.dumps(body).encode())
    monkeypatch.setattr(ig.urllib.request, "urlopen", urlopen)
    return calls


def test_graph_error_carries_code_and_subcode(monkeypatch):
    fake_http_error(monkeypatch, 400, {"error": {"message": "spam", "code": 4, "error_subcode": 2207051}})
    with pytest.raises(ig.IGError) as e:
        ig.post("/1/media_publish", "tok", creation_id="9")
    assert (e.value.code, e.value.subcode) == (4, 2207051)


def test_non_json_error_keeps_status_and_text(monkeypatch):
    fake_http_error(monkeypatch, 502, "<html>bad gateway</html>")
    with pytest.raises(ig.IGError) as e:
        ig.get("/me", "tok")
    assert (e.value.code, e.value.subcode, e.value.message) == (502, None, "<html>bad gateway</html>")


def test_create_reel_sends_trial_and_ai_label_and_omits_empty_collaborators(monkeypatch):
    calls = fake_responses(monkeypatch, {"id": "c1"})
    cid = ig.create_reel("1789", "tok", "https://x/v.mp4", "hi", thumb_offset_ms=1500,
                         trial=True, collaborators=[], ai_label=True)
    method, path, p = calls[0]
    assert (cid, method, path) == ("c1", "POST", "/v26.0/1789/media")
    assert p["media_type"] == "REELS" and p["share_to_feed"] == "true" and p["thumb_offset"] == "1500"
    assert p["is_ai_generated"] == "true"
    assert p["trial_params"] == '{"graduation_strategy":"SS_PERFORMANCE"}'
    assert p["access_token"] == "tok"
    assert "collaborators" not in p


def test_create_reel_plain_sends_collaborators_only(monkeypatch):
    calls = fake_responses(monkeypatch, {"id": "c2"})
    ig.create_reel("1789", "tok", "u", "c", thumb_offset_ms=0, trial=False, collaborators=["a", "b"], ai_label=False)
    p = calls[0][2]
    assert json.loads(p["collaborators"]) == ["a", "b"]
    assert "trial_params" not in p and "is_ai_generated" not in p


def test_wait_container_polls_while_copyright_in_progress(monkeypatch):
    fake_responses(monkeypatch,
                   {"status_code": "IN_PROGRESS"},
                   {"status_code": "FINISHED", "copyright_check_status": {"status": "in_progress"}},
                   {"status_code": "FINISHED", "copyright_check_status": {"status": "completed", "matches_found": False}})
    c = ig.wait_container("c1", "tok", copyright=True, every=0)
    assert c["copyright_check_status"]["status"] == "completed"


def test_wait_container_raises_on_error(monkeypatch):
    fake_responses(monkeypatch, {"status_code": "ERROR"})
    with pytest.raises(ig.IGError, match="container ERROR"):
        ig.wait_container("c1", "tok", copyright=False, every=0)


def test_wait_container_times_out(monkeypatch):
    fake_responses(monkeypatch, *[{"status_code": "IN_PROGRESS"}] * 3)
    clock = iter([0, 300, 700])
    monkeypatch.setattr(ig.time, "monotonic", lambda: next(clock))
    with pytest.raises(ig.IGError, match="container timeout"):
        ig.wait_container("c1", "tok", copyright=False, every=0, limit=600)


def test_media_insights_fills_missing_with_zero(monkeypatch):
    fake_responses(monkeypatch, {"data": [{"name": "views", "values": [{"value": 42}]}]})
    m = ig.media_insights("m1", "tok")
    assert m["views"] == 42 and m["reach"] == 0 and m["ig_reels_avg_watch_time"] == 0
    assert len(m) == 7


def test_account_views_parses_breakdown(monkeypatch):
    calls = fake_responses(monkeypatch, {"data": [{"name": "views", "total_value": {"value": 1000, "breakdowns": [{"results": [
        {"dimension_values": ["FOLLOWER"], "value": 200},
        {"dimension_values": ["NON_FOLLOWER"], "value": 800}]}]}}]})
    v = ig.account_views("1789", "tok", date(2026, 10, 1), date(2026, 10, 2))
    assert v == {"total": 1000, "follower": 200, "non_follower": 800}
    p = calls[0][2]
    assert p["breakdown"] == "follower_type" and p["since"] == "1790812800"


def test_account_views_falls_back_without_breakdown(monkeypatch):
    calls = fake_responses(monkeypatch, ig.IGError(100, None, "bad breakdown"),
                           {"data": [{"name": "views", "total_value": {"value": 500}}]})
    v = ig.account_views("1789", "tok", date(2026, 10, 1), date(2026, 10, 2))
    assert v == {"total": 500, "follower": None, "non_follower": None}
    assert "breakdown" not in calls[1][2]


def test_refresh_parses(monkeypatch):
    calls = fake_responses(monkeypatch, {"access_token": "new", "token_type": "bearer", "expires_in": 5184000})
    assert ig.refresh("old") == ("new", 5184000)
    assert calls[0][1] == "/refresh_access_token" and calls[0][2]["grant_type"] == "ig_refresh_token"


def test_publishing_limit(monkeypatch):
    fake_responses(monkeypatch, {"data": [{"config": {"quota_total": 50}, "quota_usage": 3}]})
    assert ig.publishing_limit("1789", "tok") == (3, 50)


def test_fake_ig_records_create_reel(monkeypatch):
    f = FakeIG()
    f.install(monkeypatch)
    assert ig.create_reel("1789", "tok", "u", "c", thumb_offset_ms=0, trial=True, collaborators=[], ai_label=True) == "c1"
    assert f.created[0]["trial"] is True and f.created[0]["user_id"] == "1789"
    f.reject_trial = True
    with pytest.raises(ig.IGError):
        ig.create_reel("1789", "tok", "u", "c", thumb_offset_ms=0, trial=True, collaborators=[], ai_label=True)
    assert ig.publish("1789", "tok", "c1") == "m1" and f.published == ["c1"]
