import os
import sqlite3

from pages import cli


def test_init_twice_leaves_two_pages(tmp_path, monkeypatch):
    monkeypatch.setattr("pages.config.HOME", tmp_path)
    cli.main(["init"])
    cli.main(["init"])
    assert sqlite3.connect(tmp_path / "pages.db").execute("select count(*) from pages").fetchone()[0] == 2


def test_env_file_fills_missing_keys_only(tmp_path, monkeypatch):
    f = tmp_path / "musubi-pages.env"
    f.write_text("# stock footage\n\nPEXELS_KEY=abc=1\n PIXABAY_KEY = xyz \nnot a line\n")
    monkeypatch.delenv("PEXELS_KEY", raising=False)
    monkeypatch.setenv("PIXABAY_KEY", "already")
    cli.load_env(f)
    assert os.environ["PEXELS_KEY"] == "abc=1" and os.environ["PIXABAY_KEY"] == "already"
    cli.load_env(tmp_path / "missing.env")
