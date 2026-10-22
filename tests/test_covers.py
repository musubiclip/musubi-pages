import subprocess

from helpers import add_clip
from PIL import Image

from pages import cli, covers, store


def test_cover_has_the_border_and_the_badge_inside_the_grid_crop(tmp_path, cfg):
    frame = tmp_path / "f.jpg"
    Image.new("RGB", (540, 960), (0, 0, 0)).save(frame)
    img = Image.open(covers.make_cover(frame, cfg.pages["tech_bawaal"], tmp_path / "c.jpg"))
    assert img.size == (1080, 1920)
    assert all(abs(a - b) < 12 for a, b in zip(img.getpixel((4, 960)), (0x25, 0x6D, 0xFD)))
    badge = img.crop((700, 240, 1060, 600))  # top right of the centre 3:4
    assert sum(badge.convert("L").histogram()[200:]) > 5000  # white ring and avatar


def test_a_page_without_an_avatar_gets_the_border_only(tmp_path, cfg):
    frame = tmp_path / "f.jpg"
    Image.new("RGB", (1080, 1920), (0, 0, 0)).save(frame)
    page = cfg.pages["tech_bawaal"]
    page.avatar = ""
    img = Image.open(covers.make_cover(frame, page, tmp_path / "c.jpg"))
    assert max(img.getpixel((900, 400))) < 20


def test_cli_rebuilds_covers_for_rendered_clips(tmp_path, local_store, monkeypatch):
    monkeypatch.setattr("pages.config.HOME", tmp_path)
    cli.main(["init"])
    from pages import db as dbm
    d = dbm.connect()
    video = tmp_path / "v.mp4"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "color=c=red:s=108x192:d=2",
                    str(video)], check=True)
    cid = add_clip(d, "tech_bawaal", "draft")
    d.execute("update clips set file_key = ? where id = ?", (f"clips/{cid}.mp4", cid))
    d.commit()
    store.put(f"clips/{cid}.mp4", video)
    cli.main(["covers", "--ids", str(cid)])
    key = d.execute("select cover_key from clips where id = ?", (cid,)).fetchone()[0]
    assert key == f"clips/{cid}-cover.jpg" and store.exists(key)
