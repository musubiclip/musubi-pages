import pytest

from pages import config, db
from pages.config import ROOT


def test_load_reads_the_two_pilot_pages():
    cfg = config.load()
    assert set(cfg.pages) == {"podcastbawaal", "tech_bawaal"}
    assert cfg.pages["podcastbawaal"].pipeline == "clips"
    assert cfg.pages["tech_bawaal"].pipeline == "clips" and cfg.pages["tech_bawaal"].clips_per_video == 3
    assert cfg.pages["tech_bawaal"].window == (9, 23) and cfg.pages["tech_bawaal"].daily_target == 1


def test_youtube_source_needs_a_permission_record(tmp_path):
    p = tmp_path / "p.toml"
    p.write_text((ROOT / "pages.toml").read_text() + '\n[[sources]]\nid = "x"\npage = "podcastbawaal"\n'
                 'kind = "youtube_channel"\nurl = "https://www.youtube.com/@x"\n')
    with pytest.raises(ValueError, match="x: permission needs who, when, how, proof"):
        config.load(p)


def test_podcast_fixture_adds_a_source(cfg_with_podcast):
    s = cfg_with_podcast.sources["pod"]
    assert s.collab_ok and s.instagram == "podofficial" and s.since.year == 2026


def test_schema_has_the_design_tables(tmp_path):
    names = {r[0] for r in db.connect(tmp_path / "t.db").execute("select name from sqlite_master where type='table'")}
    assert {"pages", "source_videos", "clips", "insights", "account_daily", "events"} <= names


def test_tech_bawaal_opens_on_a_headline_and_others_on_the_spotlight():
    pages = config.load().pages
    assert (pages["tech_bawaal"].hook_style, pages["tech_bawaal"].brand_tag) == ("headline", "TECH BAWAAL")
    assert pages["podcastbawaal"].hook_style == "spotlight" and pages["podcastbawaal"].brand_tag == ""


def test_an_unknown_hook_style_is_refused(tmp_path):
    p = tmp_path / "pages.toml"
    p.write_text((config.ROOT / "pages.toml").read_text().replace('hook_style = "headline"', 'hook_style = "banner"'))
    with pytest.raises(ValueError, match="hook_style"):
        config.load(p)
