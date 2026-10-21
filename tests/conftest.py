import pytest

from pages import config, db


@pytest.fixture
def d(tmp_path):
    conn = db.connect(tmp_path / "t.db")
    db.add_pages(conn, config.load())
    return conn


@pytest.fixture
def cfg():
    return config.load()


@pytest.fixture
def local_store(tmp_path, monkeypatch):
    path = tmp_path / "store"
    monkeypatch.setenv("PAGES_STORE", str(path))
    return path


@pytest.fixture
def cfg_with_podcast(tmp_path):
    p = tmp_path / "pages.toml"
    p.write_text((config.ROOT / "pages.toml").read_text() + """
[[sources]]
id = "pod"
page = "podcastbawaal"
kind = "youtube_channel"
url = "https://www.youtube.com/@pod"
instagram = "podofficial"
permission = {who = "Pod Host", when = "2026-10-25", how = "email", proof = "https://drive.google.com/x"}
collab_ok = true
since = 2026-10-01
""")
    return config.load(p)


@pytest.fixture
def fake_ig(monkeypatch):
    from fake_ig import FakeIG  # tests/fake_ig.py comes from another work package
    f = FakeIG()
    f.install(monkeypatch)
    return f
