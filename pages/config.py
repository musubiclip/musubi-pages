import os
import tomllib
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HOME = Path(os.environ.get("PAGES_HOME", Path.home() / "MusubiPages"))
os.environ.setdefault("MUSUBI_CLIPS_DIR", str(HOME / "work"))


@dataclass
class Page:
    handle: str
    pipeline: str
    voice: str
    window: tuple[int, int]
    daily_target: int
    theme: dict
    music: list[str] = field(default_factory=list)
    music_volume: float = 0.10  # bed level when nobody speaks; ducks to 75% under speech
    clips_per_video: int = 3
    topics: str = ""
    sfx: bool = True  # sound effects on the hook, cards and cuts (clip pages)
    active: bool = True
    queries: list[str] = field(default_factory=list)  # Creative Commons YouTube searches: any page with these gets visual reels
    hook_style: str = "spotlight"  # "headline": a news headline with the brand tag opens every reel and is its cover
    brand_tag: str = ""  # small caps over the headline, such as "TECH BAWAAL"
    avatar: str = ""  # profile picture (repo-relative path): a round badge on every reel cover


@dataclass
class Source:
    id: str
    page: str
    kind: str
    url: str
    instagram: str | None = None
    permission: dict = field(default_factory=dict)
    collab_ok: bool = False
    since: date | None = None


@dataclass
class Config:
    pages: dict[str, Page]
    sources: dict[str, Source]
    api: dict[str, bool]


def load(path: Path = ROOT / "pages.toml") -> Config:
    raw = tomllib.loads(Path(path).read_text())
    pages = {}
    for handle, p in raw.get("pages", {}).items():
        page = Page(handle=handle, **{**p, "window": tuple(p["window"])})
        lo, hi = page.window
        if not 0 <= lo < hi <= 24:
            raise ValueError(f"{handle}: window must lie within 0 to 24")
        if page.hook_style not in ("spotlight", "headline"):
            raise ValueError(f"{handle}: hook_style must be spotlight or headline")
        if not 1 <= page.daily_target <= 3:
            raise ValueError(f"{handle}: daily_target must be 1 to 3")
        pages[handle] = page
    sources = {}
    for s in raw.get("sources", []):
        src = Source(**s)
        if src.page not in pages:
            raise ValueError(f"{src.id}: unknown page {src.page}")
        if src.kind == "youtube_channel" and not {"who", "when", "how", "proof"} <= set(src.permission):
            raise ValueError(f"{src.id}: permission needs who, when, how, proof")
        sources[src.id] = src
    return Config(pages=pages, sources=sources, api=raw.get("api", {}))
