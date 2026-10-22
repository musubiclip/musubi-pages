"""Branded reel covers: the 1.3 s frame, a border in the page's colour and its avatar as a round badge."""
import subprocess
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

from pages import config, store

W, H = 1080, 1920
GRID_TOP = (H - W * 4 // 3) // 2  # 240: Instagram's profile grid shows the centre 3:4
BORDER, BADGE, RING, MARGIN = 16, 230, 8, 44


def make_cover(frame: Path, page, out: Path) -> Path:
    img = Image.open(frame).convert("RGB").resize((W, H))
    hot = page.theme.get("hot", "#ffffff")
    ImageDraw.Draw(img).rectangle((0, 0, W - 1, H - 1), outline=hot, width=BORDER)
    avatar = config.ROOT / page.avatar if page.avatar else None
    if avatar and avatar.is_file():
        size = BADGE + 2 * RING
        x, y = W - MARGIN - size, GRID_TOP + MARGIN
        mask = Image.new("L", (size, size))
        ImageDraw.Draw(mask).ellipse((0, 0, size - 1, size - 1), fill=255)
        shadow = Image.new("L", (W, H))
        shadow.paste(mask.point(lambda v: v * 0.55), (x + 6, y + 12))
        img.paste((0, 0, 0), mask=shadow.filter(ImageFilter.GaussianBlur(14)))
        img.paste((255, 255, 255), (x, y), mask)
        face = Image.open(avatar).convert("RGB").resize((BADGE, BADGE), Image.LANCZOS)
        inner = Image.new("L", (BADGE, BADGE))
        ImageDraw.Draw(inner).ellipse((0, 0, BADGE - 1, BADGE - 1), fill=255)
        img.paste(face, (x + RING, y + RING), inner)
    img.save(out, "JPEG", quality=90)
    return out


def rebuild(db, cfg, ids: list[int] | None = None) -> list[int]:
    """Covers for already-rendered clips, from the 1.3 s frame of their mp4; the ids done."""
    rows = db.execute("select id, page, file_key from clips where status in ('draft', 'approved', 'scheduled') "
                      "and file_key is not null").fetchall()
    done = []
    with tempfile.TemporaryDirectory() as tmp:
        for r in rows:
            if (ids and r["id"] not in ids) or r["page"] not in cfg.pages:
                continue
            video, frame = Path(tmp) / f"{r['id']}.mp4", Path(tmp) / f"{r['id']}.jpg"
            store.get(r["file_key"], video)
            subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-ss", "1.3", "-i", str(video),
                            "-frames:v", "1", "-q:v", "2", str(frame)], check=True)
            key = f"clips/{r['id']}-cover.jpg"
            store.put(key, make_cover(frame, cfg.pages[r["page"]], Path(tmp) / f"{r['id']}-cover.jpg"))
            db.execute("update clips set cover_key = ? where id = ?", (key, r["id"]))
            db.commit()
            done.append(r["id"])
    return done
