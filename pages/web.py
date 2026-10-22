"""Review page: approve, edit or reject drafts and see page health. Behind Cloudflare Access when deployed."""
import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import urlparse

import jwt
from fastapi import Depends, FastAPI, Form, HTTPException, Request
from fastapi.responses import FileResponse, PlainTextResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from pages import accounts, config, db as dbm, insights, store

app = FastAPI()
templates = Jinja2Templates(directory=Path(__file__).parent / "templates")
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
        return PlainTextResponse("forbidden", status_code=403)  # another site posting a form here
    if not _allowed(request):
        return PlainTextResponse("forbidden", status_code=403)
    return await call_next(request)


def _json(text, default):
    return json.loads(text) if text else default


def _page(db, cfg, handle, now):
    p = db.execute("select * from pages where handle = ?", (handle,)).fetchone()
    expires = datetime.fromisoformat(p["token_expires_at"]) if p["token"] and p["token_expires_at"] else None
    checked = datetime.fromisoformat(p["status_checked_at"]) if p["status_checked_at"] else None
    counts = dict(db.execute("select status, count(*) from clips where page = ? and status in "
                             "('approved', 'scheduled') group by status", (handle,)).fetchall())
    drafts = db.execute("select * from clips where page = ? and status = 'draft' order by id", (handle,)).fetchall()
    return {"handle": handle, "paused_at": p["paused_at"], "pause_reason": p["pause_reason"],
            "connected": bool(expires and expires > now),
            "reconnect": not (expires and expires > now + timedelta(days=10)),
            "expires": p["token_expires_at"], "status_checked_at": p["status_checked_at"],
            "status_due": not checked or now - checked > timedelta(days=7),
            "metrics": insights.page_metrics(db, handle, now),
            "approved": counts.get("approved", 0), "scheduled": counts.get("scheduled", 0),
            "drafts": [_draft(db, cfg, c) for c in drafts]}


def _draft(db, cfg, c):
    moment, layer, script = _json(c["moment"], {}), _json(c["layer"], {}), _json(c["script"], {})
    sv = db.execute("select source_id, note from source_videos where video_id = ?", (c["video_id"],)).fetchone()
    return {"id": c["id"], "video": store.url(c["file_key"], 3600) if c["file_key"] else None,
            "hook": moment.get("hook_text") or script.get("hook_text"), "layer": layer,
            "flags": layer.get("flags") or script.get("flags") or [], "claims": script.get("claims", []),
            "credits": _json(c["credits"], []), "caption": c["caption"] or "",
            "source": cfg.sources.get(sv["source_id"]) if sv and sv["source_id"] else None,
            "note": sv["note"] if sv else None}


PROBLEM_EVENTS = ("publish_error", "tick_failed", "token_refresh_failed", "token_invalid", "bad_url",
                  "insights_failed", "copyright_match", "paused", "permalink_failed", "source_withdrawn")


def _problems(db, now):
    since = (now - timedelta(days=7)).isoformat()
    clips = db.execute("select page, kind, reason from clips where status = 'failed' and created_at >= ? "
                       "order by id desc limit 50", (since,)).fetchall()
    videos = db.execute("select coalesce(title, url, video_id) as name, status, note from source_videos "
                        "where status in ('skipped', 'failed') and created_at >= ? order by id desc limit 50",
                        (since,)).fetchall()
    events = db.execute(f"select page, kind, detail, count(*) as n, max(at) as last from events "
                        f"where kind in ({', '.join('?' * len(PROBLEM_EVENTS))}) and at >= ? "
                        f"group by kind, detail order by last desc limit 50", (*PROBLEM_EVENTS, since)).fetchall()
    return {"clips": clips, "videos": videos, "events": events}


@app.get("/")
async def review(request: Request, db=Depends(get_db), cfg=Depends(get_cfg)):
    now = datetime.now(UTC)
    dbm.add_pages(db, cfg)  # works before `pages init`
    return templates.TemplateResponse(request, "review.html", {
        "pages": [_page(db, cfg, h, now) for h in cfg.pages], "problems": _problems(db, now),
        "link_pages": [h for h, p in cfg.pages.items() if p.pipeline == "clips"]})


def _home():
    return RedirectResponse("/", status_code=303)


@app.post("/clips/{cid}/approve")
async def approve(cid: int, caption: str = Form(""), db=Depends(get_db)):
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
    return _home()


@app.post("/clips/{cid}/reject")
async def reject(cid: int, reason: str = Form(""), db=Depends(get_db)):
    if not reason.strip():
        raise HTTPException(400, "a reason is required")
    cur = db.execute("update clips set status = 'rejected', reason = ? where id = ? and status = 'draft'",
                     (reason.strip(), cid))
    db.commit()
    if not cur.rowcount:
        raise HTTPException(409, "clip is not a draft")
    return _home()


@app.post("/pages/{handle}/unpause")
async def unpause(handle: str, db=Depends(get_db)):
    accounts.unpause(db, handle, datetime.now(UTC))
    return _home()


@app.post("/pages/{handle}/status")
async def account_status(handle: str, recommendable: str = Form(...), db=Depends(get_db)):
    if recommendable not in ("yes", "no"):
        raise HTTPException(400, "recommendable must be yes or no")
    now = datetime.now(UTC)
    db.execute("update pages set status_checked_at = ?, recommendable = ? where handle = ?",
               (now.isoformat(), recommendable, handle))
    db.commit()
    if recommendable == "no":
        accounts.pause(db, handle, "not recommendable", now)
    return _home()


@app.post("/links")
async def links(url: str = Form(...), page: str = Form(...), note: str = Form(""), db=Depends(get_db),
          cfg=Depends(get_cfg)):
    from pages.clips_pipeline import add_link
    try:
        add_link(db, cfg, url, page, note)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return _home()


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
