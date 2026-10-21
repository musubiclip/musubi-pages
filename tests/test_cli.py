import sqlite3

from pages import cli


def test_init_twice_leaves_two_pages(tmp_path, monkeypatch):
    monkeypatch.setattr("pages.config.HOME", tmp_path)
    cli.main(["init"])
    cli.main(["init"])
    assert sqlite3.connect(tmp_path / "pages.db").execute("select count(*) from pages").fetchone()[0] == 2
