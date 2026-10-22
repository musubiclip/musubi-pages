from fake_ig import FakeIG

from pages import store, verify


def test_verify_reports_each_unknown_and_never_publishes(d, monkeypatch, local_store):
    fake = FakeIG(container={"status_code": "FINISHED",
                             "copyright_check_status": {"status": "completed", "matches_found": False}})
    fake.install(monkeypatch)
    monkeypatch.setattr(store, "url", lambda k, s=3600: "https://example.test/" + k)
    out = verify.run(d, "tech_bawaal")
    assert out["publishing_limit"] == {"usage": 0, "total": 50}
    assert out["trial_params"] == "accepted" and out["ai_label"] == "accepted"
    assert out["copyright_check_status"] == {"status": "completed", "matches_found": False}
    assert "follower_type_views" in out and fake.published == []
    assert any(k.startswith("clips/verify-") for k in store.keys("clips/"))


def test_trial_params_rejection_is_reported_not_raised(d, monkeypatch, local_store):
    fake = FakeIG(reject_trial=True)
    fake.install(monkeypatch)
    monkeypatch.setattr(store, "url", lambda k, s=3600: "https://example.test/" + k)
    out = verify.run(d, "tech_bawaal")
    assert out["trial_params"].startswith("rejected:") and out["ai_label"] == "accepted"
