"""JSON API for the review app (web/) plus the built app itself. Behind Cloudflare Access when deployed."""
import json
import os
from datetime import UTC, datetime, timedelta
from urllib.parse import urlparse

import jwt
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, StrictBool

from pages import accounts, config, db as dbm, ig, insights, store
from pages.schedule import IST

app = FastAPI()
DIST = config.ROOT / "web" / "dist"
_jwks: dict = {}  # one PyJWKClient per Access team, so the certs are cached


async def get_db():
    db = dbm.connect()
    try:
        yield db
    finally:
        db.close()


def get_cfg():
    return config.load()


def _allowed(request: Request) -> bool:
    aud = os.environ.get("CF_ACCESS_AUD")
    if not aud:
        return True
    token = request.headers.get("Cf-Access-Jwt-Assertion")
    if not token:
        return False
    team = os.environ.get("CF_ACCESS_TEAM", "")
    if team not in _jwks:
        _jwks[team] = jwt.PyJWKClient(f"https://{team}/cdn-cgi/access/certs")
    try:
        key = _jwks[team].get_signing_key_from_jwt(token).key
        claims = jwt.decode(token, key, algorithms=["RS256"], audience=aud,
                            options={"require": ["exp", "email"]})
    except Exception:  # any bad, expired or unverifiable token is a plain 403
        return False
    return str(claims.get("email", "")).lower().endswith("@musubiclip.com")


@app.middleware("http")
async def access(request: Request, call_next):
    if os.environ.get("PAGES_STORE", "").startswith("s3://") and not os.environ.get("CF_ACCESS_AUD"):
        return PlainTextResponse("Access not configured", status_code=503)  # never open on a deployed store
    origin = request.headers.get("origin")
    if request.method == "POST" and origin and urlparse(origin).netloc != request.headers.get("host"):
        return PlainTextResponse("forbidden", status_code=403)  # another site posting here
    if not _allowed(request):
        return PlainTextResponse("forbidden", status_code=403)
    return await call_next(request)


@app.exception_handler(RequestValidationError)
async def bad_body(request: Request, exc: RequestValidationError):
    # 400 like every other refusal; names the field, never echoes the input (it may be a token).
    msg = "; ".join(f"{e['loc'][-1]}: {e['msg']}" for e in exc.errors())
    return JSONResponse({"detail": msg}, status_code=400)


def _json(text, default):
    return json.loads(text) if text else default


def _page(db, cfg, handle, now):
    p = db.execute("select * from pages where handle = ?", (handle,)).fetchone()
    expires = datetime.fromisoformat(p["token_expires_at"]) if p["token"] and p["token_expires_at"] else None
    checked = datetime.fromisoformat(p["status_checked_at"]) if p["status_checked_at"] else None
    counts = dict(db.execute("select status, count(*) from clips where page = ? group by status", (handle,)).fetchall())
    c = cfg.pages[handle]
    return {"handle": handle, "pipeline": c.pipeline,
            "connected": bool(expires and expires > now),
            "reconnect": not (expires and expires > now + timedelta(days=10)),
            "token_expires_at": p["token_expires_at"] if p["token"] else None,
            "paused": bool(p["paused_at"]), "paused_at": p["paused_at"], "pause_reason": p["pause_reason"],
            "status_due": not checked or now - checked > timedelta(days=7),
            "recommendable": {"yes": True, "no": False}.get(p["recommendable"]),
            "status_checked_at": p["status_checked_at"],
            "metrics": insights.page_metrics(db, handle, now),
            "counts": {k: counts.get(k, 0) for k in ("draft", "approved", "scheduled", "published")},
            "reels": [_reel(r) for r in db.execute(
                "select * from clips where page = ? and status in ('approved', 'scheduled', 'publishing', 'published') "
                "order by coalesce(published_at, scheduled_at, created_at) desc limit 60", (handle,))],
            "settings": {"voice": c.voice, "window": list(c.window), "daily_target": c.daily_target,
                         "theme": c.theme}}


def _reel(c):
    """An approved, scheduled or published reel, as the page view's grid shows it."""
    moment = _json(c["moment"], {})
    return {"id": c["id"], "kind": c["kind"], "status": "scheduled" if c["status"] == "publishing" else c["status"],
            "hook": moment.get("hook_text") or moment.get("headline") or _json(c["script"], {}).get("hook_text"),
            "video_url": store.url(c["file_key"], 3600) if c["file_key"] else None,
            "cover_url": store.url(c["cover_key"], 3600) if c["cover_key"] else None,
            "scheduled_at": c["scheduled_at"], "published_at": c["published_at"], "permalink": c["permalink"]}


def _source(src):
    if not src:
        return None
    perm = src.permission
    summary = (f"Permission from {perm['who']} on {perm['when']} by {perm['how']}" if perm.get("who")
               else perm.get("licence", ""))
    return {"name": src.id, "url": src.url, "permission": summary, "proof": perm.get("proof"),
            "instagram": f"https://www.instagram.com/{src.instagram}/" if src.instagram else None}


def _credit(c):
    return {"text": c.get("credit", ""), "url": c.get("page_url")} if isinstance(c, dict) else {"text": c, "url": None}


def _draft(db, cfg, c):
    moment, layer, script = _json(c["moment"], {}), _json(c["layer"], {}), _json(c["script"], {})
    sv = db.execute("select source_id, note from source_videos where video_id = ?", (c["video_id"],)).fetchone()
    return {"id": c["id"], "page": c["page"], "kind": c["kind"], "created_at": c["created_at"],
            "video_url": store.url(c["file_key"], 3600) if c["file_key"] else None,
            "cover_url": store.url(c["cover_key"], 3600) if c["cover_key"] else None,
            "hook": moment.get("hook_text") or moment.get("headline") or script.get("hook_text"),
            "layer": {k: layer.get(k) for k in ("intro", "takeaway", "cards")} if layer else None,
            "flags": layer.get("flags") or script.get("flags") or [], "claims": script.get("claims", []),
            "credits": [_credit(x) for x in _json(c["credits"], [])], "caption": c["caption"] or "",
            "source": _source(cfg.sources.get(sv["source_id"]) if sv and sv["source_id"] else None),
            "note": sv["note"] if sv else None}


PROBLEM_EVENTS = ("publish_error", "tick_failed", "token_refresh_failed", "token_invalid", "bad_url",
                  "insights_failed", "copyright_match", "paused", "permalink_failed", "source_withdrawn")


def _problems(db, now):
    since = (now - timedelta(days=7)).isoformat()
    clips = db.execute("select created_at as at, page, 'clip_failed' as kind, reason as detail, 1 as count "
                       "from clips where status = 'failed' and created_at >= ? order by id desc limit 50", (since,))
    videos = db.execute("select created_at as at, page, 'video_' || status as kind, "
                        "coalesce(title, url, video_id) || ': ' || coalesce(note, '') as detail, 1 as count "
                        "from source_videos where status in ('skipped', 'failed') and created_at >= ? "
                        "order by id desc limit 50", (since,))
    events = db.execute(f"select max(at) as at, page, kind, detail, count(*) as count from events "
                        f"where kind in ({', '.join('?' * len(PROBLEM_EVENTS))}) and at >= ? "
                        f"group by kind, detail order by at desc limit 50", (*PROBLEM_EVENTS, since))
    rows = [dict(r) for q in (clips, videos, events) for r in q.fetchall()]
    return sorted(rows, key=lambda r: r["at"] or "", reverse=True)


@app.get("/api/state")
async def state(db=Depends(get_db), cfg=Depends(get_cfg)):
    now = datetime.now(UTC)
    dbm.add_pages(db, cfg)  # works before `pages init`
    drafts = db.execute("select * from clips where status = 'draft' order by page, id").fetchall()
    return {"pages": [_page(db, cfg, h, now) for h in cfg.pages],
            "drafts": [_draft(db, cfg, c) for c in drafts if c["page"] in cfg.pages],
            "problems": _problems(db, now)}


OK = {"ok": True}


class Approve(BaseModel):
    caption: str = ""


class Reject(BaseModel):
    reason: str = ""


class Status(BaseModel):
    recommendable: StrictBool


class Link(BaseModel):
    url: str
    page: str
    note: str = ""


class Connect(BaseModel):
    token: str


class Reschedule(BaseModel):
    at: datetime  # with its offset, e.g. 2026-10-23T09:30:00+05:30


@app.post("/api/clips/{cid}/approve")
async def approve(cid: int, body: Approve, db=Depends(get_db)):
    caption = body.caption
    if len(caption) > 2200:
        raise HTTPException(400, "caption is over 2200 characters")
    if not caption.strip():
        raise HTTPException(400, "caption is empty")
    if caption.count("#") > 5:
        raise HTTPException(400, "more than 5 hashtags")
    row = db.execute("select kind, credits, caption from clips where id = ?", (cid,)).fetchone()
    if row:
        if row["kind"] == "script":
            lines = [c["credit"] for c in _json(row["credits"], []) if isinstance(c, dict)]
        else:
            lines = [x.strip() for x in (row["caption"] or "").splitlines() if x.strip().startswith("🎙️")]
        missing = [x for x in lines if x not in caption]
        if missing:
            raise HTTPException(400, f"caption drops the credit: {missing[0]}")
    cur = db.execute("update clips set status = 'approved', caption = ? where id = ? and status = 'draft'",
                     (caption, cid))
    db.commit()
    if not cur.rowcount:
        raise HTTPException(409, "clip is not a draft")
    return OK


@app.post("/api/clips/{cid}/reject")
async def reject(cid: int, body: Reject, db=Depends(get_db)):
    if not body.reason.strip():
        raise HTTPException(400, "a reason is required")
    cur = db.execute("update clips set status = 'rejected', reason = ? where id = ? and status = 'draft'",
                     (body.reason.strip(), cid))
    db.commit()
    if not cur.rowcount:
        raise HTTPException(409, "clip is not a draft")
    return OK


@app.post("/api/clips/{cid}/unschedule")
async def unschedule(cid: int, db=Depends(get_db)):
    """Take a scheduled reel off the schedule for good; one already being posted can't be stopped."""
    cur = db.execute("update clips set status = 'rejected', reason = 'removed from the schedule', scheduled_at = null "
                     "where id = ? and status = 'scheduled'", (cid,))
    db.commit()
    if not cur.rowcount:
        raise HTTPException(409, "reel is not scheduled (it may be posting right now)")
    return OK


@app.post("/api/clips/{cid}/reschedule")
async def reschedule(cid: int, body: Reschedule, db=Depends(get_db), cfg=Depends(get_cfg)):
    if body.at.tzinfo is None:
        raise HTTPException(400, "time needs a timezone")
    at = body.at.astimezone(UTC)
    if at < datetime.now(UTC) + timedelta(minutes=2):
        raise HTTPException(400, "pick a time in the future")
    row = db.execute("select page from clips where id = ? and status = 'scheduled'", (cid,)).fetchone()
    if not row:
        raise HTTPException(409, "reel is not scheduled (it may be posting right now)")
    lo, hi = cfg.pages[row["page"]].window
    if not lo <= at.astimezone(IST).hour < hi:  # the publisher never posts outside the window
        raise HTTPException(400, f"outside the posting window, {lo}:00 to {hi}:00 IST")
    db.execute("update clips set scheduled_at = ? where id = ? and status = 'scheduled'", (at.isoformat(), cid))
    db.commit()
    return OK


@app.post("/api/pages/{handle}/unpause")
async def unpause(handle: str, db=Depends(get_db)):
    accounts.unpause(db, handle, datetime.now(UTC))
    return OK


@app.post("/api/pages/{handle}/status")
async def account_status(handle: str, body: Status, db=Depends(get_db)):
    now = datetime.now(UTC)
    answer = "yes" if body.recommendable else "no"
    db.execute("update pages set status_checked_at = ?, recommendable = ? where handle = ?",
               (now.isoformat(), answer, handle))
    db.commit()
    if not body.recommendable:
        accounts.pause(db, handle, "not recommendable", now)
    return OK


@app.post("/api/links")
async def links(body: Link, db=Depends(get_db), cfg=Depends(get_cfg)):
    from pages.clips_pipeline import add_link
    try:
        add_link(db, cfg, body.url, body.page, body.note)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return OK


@app.post("/api/pages/{handle}/connect")
async def connect(handle: str, body: Connect, db=Depends(get_db), cfg=Depends(get_cfg)):
    try:
        accounts.connect(db, handle, body.token, datetime.now(UTC), cfg)
    except (ValueError, ig.IGError) as e:
        raise HTTPException(400, str(e).replace(body.token, "[token]"))  # never echo the token
    return OK


@app.get("/files/{key:path}")
async def files(key: str):
    if os.environ.get("PAGES_STORE", "").startswith("s3://"):
        raise HTTPException(404)
    try:
        path = store._local(store._backend()[1], key)
    except ValueError:
        raise HTTPException(404)
    # only clips: the store also holds DB backups (with tokens). Checked on the resolved path, so
    # encoded ../ in the key cannot climb out of clips/.
    if not path.is_relative_to(store._backend()[1].resolve() / "clips") or not path.is_file():
        raise HTTPException(404)
    return FileResponse(path)


if DIST.is_dir():  # last: the API routes above win
    app.mount("/", StaticFiles(directory=DIST, html=True), name="app")
else:
    @app.get("/")
    async def home():
        return PlainTextResponse("Run `npm run build` in web/ first")
