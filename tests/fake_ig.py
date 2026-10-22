"""In-memory stand-in for pages.ig, shared by every package's tests."""
from pages import ig


class FakeIG:
    def __init__(self, *, limit=(0, 50), container=None, reject_trial=False, me=None, insights=None, views=None,
                 refresh=("new-token", 5184000)):
        self.limit = limit
        self.container = container or {"status_code": "FINISHED",
                                       "copyright_check_status": {"status": "completed", "matches_found": False}}
        self.reject_trial = reject_trial
        self.fail_create = None
        self.fail_publish = None
        self.me_result = me or {"user_id": "1789", "username": "tech_bawaal", "account_type": "MEDIA_CREATOR",
                                "followers_count": 0}
        self.insights = insights or {"views": 100, "reach": 80, "likes": 5, "comments": 1, "saved": 2, "shares": 3,
                                     "ig_reels_avg_watch_time": 4000}
        self.views = views or {"total": 1000, "follower": 200, "non_follower": 800}
        self.refresh_result = refresh
        self.created, self.published, self.insight_calls, self.refreshed = [], [], [], []

    def me(self, token):
        return self.me_result

    def publishing_limit(self, user_id, token):
        return self.limit

    def create_reel(self, user_id, token, video_url, caption, *, thumb_offset_ms, trial, collaborators, ai_label):
        if self.fail_create:
            raise self.fail_create
        if self.reject_trial and trial:
            raise ig.IGError(100, None, "Invalid parameter trial_params")
        self.created.append(dict(user_id=user_id, token=token, video_url=video_url, caption=caption,
                                 thumb_offset_ms=thumb_offset_ms, trial=trial, collaborators=collaborators,
                                 ai_label=ai_label))
        return f"c{len(self.created)}"

    def get_container(self, container_id, token, *, copyright=False):
        return self.container

    def wait_container(self, container_id, token, *, copyright, every=30, limit=600):
        if self.container.get("status_code") == "ERROR":
            raise ig.IGError(-1, None, "container ERROR")
        return self.container

    def publish(self, user_id, token, container_id):
        if self.fail_publish:
            raise self.fail_publish
        self.published.append(container_id)
        return f"m{len(self.published)}"

    def media(self, media_id, token):
        return {"permalink": f"https://www.instagram.com/reel/{media_id}/"}

    def media_insights(self, media_id, token):
        self.insight_calls.append(media_id)
        return self.insights

    def account_views(self, user_id, token, since, until):
        return self.views

    def refresh(self, token):
        self.refreshed.append(token)
        return self.refresh_result

    def install(self, monkeypatch):
        # `container` is a data attribute here, so the method is get_container.
        for name in ["me", "publishing_limit", "create_reel", "wait_container", "account_views", "publish",
                     "media", "media_insights", "refresh"]:
            monkeypatch.setattr(ig, name, getattr(self, name))
        monkeypatch.setattr(ig, "container", self.get_container)
        return self
