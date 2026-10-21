from helpers import put_prepared

from pages import store


def test_local_store_round_trip(tmp_path, monkeypatch):
    monkeypatch.setenv("PAGES_STORE", str(tmp_path / "s"))
    f = tmp_path / "a.txt"; f.write_text("hi")
    store.put("work/v1/a.txt", f)
    assert store.exists("work/v1/a.txt") and store.keys("work/v1/") == ["work/v1/a.txt"]
    assert store.get("work/v1/a.txt", tmp_path / "b.txt").read_text() == "hi"
    store.put_json("jobs/fetch.json", {"a": 1})
    assert store.get_json("jobs/fetch.json") == {"a": 1} and store.get_json("nope.json", {}) == {}
    assert store.url("clips/1.mp4") == "/files/clips/1.mp4"
    store.delete("work/v1/a.txt"); assert not store.exists("work/v1/a.txt")


def test_put_prepared_writes_the_work_files(local_store):
    put_prepared(local_store, "v1", {"id": "v1"})
    assert store.keys("work/v1/") == ["work/v1/meta.json", "work/v1/source-audio.info.json",
                                      "work/v1/transcript.json", "work/v1/transcript.txt"]
    assert (local_store / "work/v1/transcript.txt").read_text() == "[0.0-3.0] Hello there.\n"


def test_local_keys_cannot_escape_the_store(local_store, tmp_path):
    import pytest
    f = tmp_path / "a.txt"; f.write_text("hi")
    for key in ["../x", "/etc/passwd"]:
        with pytest.raises(ValueError):
            store.get(key, tmp_path / "out.txt")
        with pytest.raises(ValueError):
            store.put(key, f)
