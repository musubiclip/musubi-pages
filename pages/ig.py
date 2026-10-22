"""Instagram API with Instagram Login (graph.instagram.com). Stdlib only."""
import calendar
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date

BASE = "https://graph.instagram.com/v26.0"
TIMEOUT = 60
INSIGHT_METRICS = ["views", "reach", "likes", "comments", "saved", "shares", "ig_reels_avg_watch_time"]


class IGError(Exception):
    def __init__(self, code: int, subcode: int | None, message: str):
        super().__init__(f"{code}/{subcode}: {message}")
        self.code, self.subcode, self.message = code, subcode, message


def _call(req: urllib.request.Request) -> dict:
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        text = e.read().decode(errors="replace")
        try:
            err = json.loads(text)["error"]
        except (ValueError, KeyError, TypeError):
            raise IGError(e.code, None, text[:300]) from None
        raise IGError(err.get("code", e.code), err.get("error_subcode"), err.get("message", "")) from None


def _url(path: str) -> str:
    return path if path.startswith("https://") else BASE + path


def get(path: str, token: str, **params) -> dict:
    query = urllib.parse.urlencode({**params, "access_token": token})
    return _call(urllib.request.Request(f"{_url(path)}?{query}"))


def post(path: str, token: str, **params) -> dict:
    body = urllib.parse.urlencode({**params, "access_token": token}).encode()
    return _call(urllib.request.Request(_url(path), data=body, method="POST"))


def me(token: str) -> dict:
    return get("/me", token, fields="user_id,username,account_type,followers_count")


def publishing_limit(user_id: str, token: str) -> tuple[int, int]:
    d = get(f"/{user_id}/content_publishing_limit", token, fields="config,quota_usage")["data"][0]
    return d.get("quota_usage", 0), d["config"]["quota_total"]


def create_reel(user_id: str, token: str, video_url: str, caption: str, *,
                thumb_offset_ms: int, trial: bool, collaborators: list[str], ai_label: bool) -> str:
    params = {"media_type": "REELS", "video_url": video_url, "caption": caption,
              "share_to_feed": "true", "thumb_offset": thumb_offset_ms}
    if ai_label:
        params["is_ai_generated"] = "true"
    if trial:
        params["trial_params"] = '{"graduation_strategy":"SS_PERFORMANCE"}'
    if collaborators:
        params["collaborators"] = json.dumps(collaborators)
    return post(f"/{user_id}/media", token, **params)["id"]


def container(container_id: str, token: str, *, copyright: bool = False) -> dict:
    # copyright_check_status doesn't exist under Instagram Login: asking for it fails the whole call
    return get(f"/{container_id}", token, fields="status_code,copyright_check_status" if copyright else "status_code")


def wait_container(container_id: str, token: str, *, copyright: bool, every=30, limit=600) -> dict:
    start = time.monotonic()
    while True:
        c = container(container_id, token, copyright=copyright)
        status = c.get("status_code")
        if status in ("ERROR", "EXPIRED"):
            raise IGError(-1, None, f"container {status}")
        checking = copyright and (c.get("copyright_check_status") or {}).get("status") == "in_progress"
        if status == "FINISHED" and not checking:
            return c
        if time.monotonic() - start > limit:
            raise IGError(-1, None, "container timeout")
        time.sleep(every)


def publish(user_id: str, token: str, container_id: str) -> str:
    return post(f"/{user_id}/media_publish", token, creation_id=container_id)["id"]


def media(media_id: str, token: str) -> dict:
    return get(f"/{media_id}", token, fields="permalink,timestamp")


def media_insights(media_id: str, token: str) -> dict[str, int]:
    data = get(f"/{media_id}/insights", token, metric=",".join(INSIGHT_METRICS)).get("data", [])
    got = {m["name"]: (m.get("values") or [{}])[0].get("value", 0) for m in data}
    return {name: got.get(name, 0) for name in INSIGHT_METRICS}


def account_views(user_id: str, token: str, since: date, until: date) -> dict:
    # Response shape unverified against the live API; parse defensively.
    params = {"metric": "views", "period": "day", "metric_type": "total_value",
              "since": calendar.timegm(since.timetuple()), "until": calendar.timegm(until.timetuple())}
    try:
        d = get(f"/{user_id}/insights", token, breakdown="follower_type", **params)
    except IGError:
        d = get(f"/{user_id}/insights", token, **params)
    tv = ((d.get("data") or [{}])[0]).get("total_value") or {}
    by = {}
    for r in ((tv.get("breakdowns") or [{}])[0]).get("results", []):
        by[(r.get("dimension_values") or [None])[0]] = r.get("value")
    return {"total": tv.get("value", 0), "follower": by.get("FOLLOWER"), "non_follower": by.get("NON_FOLLOWER")}


def refresh(token: str) -> tuple[str, int]:
    d = get("https://graph.instagram.com/refresh_access_token", token, grant_type="ig_refresh_token")
    return d["access_token"], d["expires_in"]
