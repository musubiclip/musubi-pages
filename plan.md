# Musubi Pages Pilot Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. Steps marked **[YOU]** need Prateek (accounts, consoles, keys, accepting invites). The agent stops at each one and waits.

**Goal:** Run `podcastbawaal` (clip pipeline) and `billikalesh` (script first pipeline) end to end: make reels with an AI original layer, review them once a day, publish through the official Instagram API at varied times, and track views.

**Architecture:** One Python package (`pages`) with a review web app and two timed commands: `pages tick` (publish, insights, tokens, backups) and `pages work` (intake, Claude, Polly, render). SQLite holds state. A small storage module puts files in a local folder or S3, and every exchange with the Mac fetcher goes through it (`jobs/`, `inbox/`, `work/`). Everything runs on the Mac first, with Claude reached through the Claude subscription (`claude -p`). The same code is then deployed to one EC2 instance in `ap-south-1` with S3 and Bedrock, behind Cloudflare Tunnel + Access.

**Tech Stack:** Python 3.12 (uv), FastAPI + Jinja2 + uvicorn, stdlib `sqlite3` and `urllib`, boto3 (S3, Polly), `anthropic` (`AnthropicBedrockMantle`) or the `claude` CLI, PyJWT, the vendored musubi-clips engine (ffmpeg, OpenCV, HyperFrames on Node 22), and yt-dlp on the Mac only. Tests use pytest.

**Spec:** `design.md` (decisions in §4 and §9 are final), `HANDOFF.md`; sources in `research/`.

## Decisions made while planning (22 Oct 2026)

- **Engine:** copy musubi-clips into `engine/` and extend it here. The outbound skill at `~/.claude/skills/musubi-clips` stays untouched.
- **Access when deployed:** Cloudflare Tunnel + Access. Google sign in is limited to `@musubiclip.com`, the instance has no inbound ports, and the app checks Access's signed header.
- **AI label:** every reel is published with `is_ai_generated=true` (each one carries a Polly voice).
- **Local first:** build and test everything on the Mac. Claude runs through the subscription (`PAGES_LLM=claude-cli`) and storage is a local folder, until the deploy task switches to Bedrock and S3. Publishing, including the API check, always needs S3, because Instagram must fetch the video from a public URL.
- **Builder's picks (design §10):**
  - Instance: `t3.medium`, x86, 4 GB. HyperFrames supports ARM Linux only through a system Chromium, so the `t4g` instances are out.
  - Model: `claude-opus-5-5`, called as `anthropic.claude-opus-5-5` on Bedrock.
  - Trial Reels: `graduation_strategy` `SS_PERFORMANCE`, because the pilot allows no manual steps except review.
  - Music library: Pixabay Music.
  - Legal pages: static pages on Cloudflare Pages.
  - Page and source settings: `pages.toml` in the repo, with no settings screens. Tokens live only in the DB, entered with `pages connect` (getpass).
- **Not automated in the pilot:**
  - Checking whether the source already posted a moment on Instagram: the Instagram Login API can't read other accounts, so the review page links the source's profile for the reviewer to check.
  - "Upload a file": it needs a Whisper path. Add both when YouTube blocks the Mac.

## Global Constraints

- Python `>=3.12,<3.13` (the engine pins it). AWS region `ap-south-1`. One EC2 instance, SQLite on its disk, one S3 bucket, Bedrock (Claude), Polly.
- Instagram API with Instagram Login, `https://graph.instagram.com/v26.0`, through a **new** Meta app (never `1074493771960727`). Scopes: `instagram_business_basic`, `instagram_business_content_publish`, `instagram_business_manage_insights`. Each page is an Instagram tester.
- Never automate follow, unfollow, like, comment or DM. No proxies, VPNs or antidetect anything. Never touch the musubi-platform repo, its Meta app, its WhatsApp number or the `musubi_clip` account.
- Never read, store or type Instagram passwords or 2FA secrets. Prateek enters them by hand; the tool only ever holds API tokens.
- English for voiceover, on screen text and captions on every page. Voices are Polly English (India).
- Posting: random times between 9am and 11pm IST, at least 3 hours apart, the page's daily target (start at 1, at most 3), an occasional skipped day, a different pattern per page. The first 7 days of each page go out as Trial Reels.
- Every clip has an original layer: a voiceover intro of 3 to 6 seconds, a takeaway of about 3 seconds, and 1 to 3 context cards. One clip goes to one page. Drop moments with music in them. The only music allowed is a bed from the licensed library.
- Clip pipeline moments are 30 to 90 seconds. Script first reels are 20 to 45 seconds. Captions: at most 5 hashtags, at most 2200 characters, and never the same text twice.
- Publish errors `2207050` and `2207051` pause the page until a person unpauses it. Other errors retry twice, then the clip is marked failed.
- Insights at 1 hour, 24 hours, 72 hours and 7 days after posting. Refresh tokens weekly, and warn on the review page 10 days before one expires.
- Media is deleted 30 days after posting. The SQLite database is backed up to S3 every night.
- When Claude refuses: check `stop_reason == "refusal"` and fail that item with the reason. (Skipped: the Bedrock client side fallback middleware; add it if refusals show up.)

## Review Focus

These are failure modes the spec implies but no ordinary test covers. Each one has a pinned test in the task named.

1. **An expired or revoked token (Graph error `190`) while clips are queued.** Expected: the page stops trying, its clips keep their place, nothing is marked failed, and the review page says "reconnect". Test: Task 6 `test_expired_token_keeps_clips_and_asks_for_reconnect`.
2. **A page is paused with clips already scheduled, then unpaused days later.** Expected: the clips get fresh future slots, never a burst of overdue posts. Test: Task 6 `test_unpause_gives_fresh_slots_not_a_burst`.
3. **The Mac sleeps for days, then the fetcher wakes to a pile of jobs.** Expected: each video is prepared once and its sections fetched once, with nothing downloaded or uploaded again. Test: Task 11 `test_fetcher_skips_work_already_in_the_store`.
4. **A pasted link from a channel that is not an allowed source, with no one off note.** Expected: it is never clipped and is skipped with a visible reason. Test: Task 11 `test_link_from_unlisted_channel_is_skipped_without_a_note`.
5. **The same YouTube video reaches a second page.** Expected: refused, because one clip goes to one page. Test: Task 11 `test_a_video_belongs_to_one_page_only`.

---

## File map

```
pyproject.toml            uv project; package "pages" + "engine"; pytest config
pages.toml                pages, sources with permission records, [api] flags (no secrets)
pages/config.py           load pages.toml into Page/Source/Config; HOME paths
pages/db.py               connect(), SCHEMA, event()
pages/store.py            local folder or S3: put/get/exists/keys/delete/put_json/get_json/url
pages/ig.py               Instagram Graph calls, IGError
pages/accounts.py         connect, pause, unpause, refresh_tokens
pages/verify.py           one-off API check (pages verify-ig)
pages/llm.py              ask(prompt, Schema) via claude CLI or Bedrock
pages/voice.py            Polly speak() with word timings
pages/writing.py          every prompt + pydantic schema: moments, translation, layer, caption, script
pages/schedule.py         pick_slot(), skipped_day()
pages/publish.py          schedule_approved(), publish_due()
pages/insights.py         fetch_due(), daily_account(), page_metrics()
pages/tick.py             tick(): publish, insights, tokens, backup, media cleanup
pages/web.py + pages/templates/review.html   review page, Access check
pages/fetcher.py          Mac side: watch, prepare, sections, cc_search
pages/clips_pipeline.py   jobs, inbox, links, pick, make_clips, step()
pages/script_pipeline.py  footage search, montage, make_reel, step()
pages/cli.py              `pages` command
engine/                   vendored musubi-clips (clipper.py, assets/, test_clipper.py)
static/                   privacy.html, data-deletion.html (Cloudflare Pages)
deploy/                   bucket.sh, bootstrap.sh, setup-instance.sh, deploy.sh, systemd units, fetcher plist
tests/                    one test file per pages module, conftest.py
```

---

## Phase 1: Foundation and the unknowns

### Task 1: Project skeleton (config, database, storage, legal pages)

**Files:**
- Create: `pyproject.toml`, `.gitignore`, `pages.toml`, `pages/__init__.py`, `pages/config.py`, `pages/db.py`, `pages/store.py`, `pages/cli.py`, `static/privacy.html`, `static/data-deletion.html`
- Test: `tests/conftest.py`, `tests/test_config.py`, `tests/test_store.py`

**Interfaces:**
- Produces:
  - `config.HOME: Path`. It reads env `PAGES_HOME`, default `~/MusubiPages`, and sets `MUSUBI_CLIPS_DIR` to `HOME/"work"` if unset.
  - `config.load(path: Path = ROOT / "pages.toml") -> Config`, where `Config(pages: dict[str, Page], sources: dict[str, Source], api: dict[str, bool])`.
  - `Page`: `handle`, `pipeline` (`"clips"`|`"script"`), `voice`, `window: tuple[int, int]`, `daily_target`, `theme: dict` (`hot`, `sun`, `font`), `music: list[str]`, `clips_per_video`, `topics`.
  - `Source`: `id`, `page`, `kind` (`"youtube_channel"`|`"pexels"`|`"pixabay"`|`"cc_youtube"`), `url`, `instagram: str | None`, `permission: dict`, `collab_ok: bool`, `since: date`.
  - `db.connect(path: Path | None = None) -> sqlite3.Connection`: default `HOME/"pages.db"`, WAL, `sqlite3.Row`, runs `SCHEMA`.
  - `db.event(db, page: str | None, kind: str, detail: str) -> None`.
  - `store.put(key, path)`, `store.get(key, path) -> Path`, `store.exists(key) -> bool`, `store.keys(prefix) -> list[str]` (sorted), `store.delete(key)`, `store.put_json(key, value)`, and `store.get_json(key, default=None)`.
  - `store.url(key, seconds=3600) -> str`: a presigned `https://` URL on S3, or `"/files/<key>"` on the local backend. The backend is chosen at call time from env `PAGES_STORE`: `s3://<bucket>`, or a folder path (default `HOME/"store"`).

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_config.py
def test_load_reads_the_two_pilot_pages():
    cfg = config.load()
    assert set(cfg.pages) == {"podcastbawaal", "billikalesh"}
    assert cfg.pages["podcastbawaal"].pipeline == "clips"
    assert cfg.pages["billikalesh"].pipeline == "script"
    assert cfg.pages["billikalesh"].window == (9, 23) and cfg.pages["billikalesh"].daily_target == 1

def test_youtube_source_needs_a_permission_record(tmp_path):
    p = tmp_path / "p.toml"
    p.write_text((ROOT / "pages.toml").read_text() + '\n[[sources]]\nid = "x"\npage = "podcastbawaal"\n'
                 'kind = "youtube_channel"\nurl = "https://www.youtube.com/@x"\n')
    with pytest.raises(ValueError, match="x: permission needs who, when, how, proof"):
        config.load(p)

def test_schema_has_the_design_tables(tmp_path):
    names = {r[0] for r in db.connect(tmp_path / "t.db").execute("select name from sqlite_master where type='table'")}
    assert {"pages", "source_videos", "clips", "insights", "account_daily", "events"} <= names

# tests/test_store.py
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
```

`tests/conftest.py` has the fixtures `d` (a temp DB), `cfg` (`config.load()`) and `local_store` (`PAGES_STORE` set to a temp folder). Every later task's tests use them.

- [ ] **Step 2: Run** `uv run pytest tests -q`. Expected: FAIL (`ModuleNotFoundError: pages`).

- [ ] **Step 3: Implement**

`pyproject.toml`:
- Python `>=3.12,<3.13`. Packages `pages` and `engine` (hatchling).
- Dependencies: `fastapi`, `uvicorn`, `jinja2`, `python-multipart`, `boto3`, `anthropic[bedrock]`, `pydantic`, `pyjwt[crypto]`, `opencv-python-headless`. Dev dependencies: `pytest`, `httpx`.
- Script `pages = "pages.cli:main"`. Pytest `testpaths = ["tests", "engine"]`, marker `slow`.

`pages.toml`:
- `podcastbawaal`: pipeline `clips`, voice `Kajal`, window `[9, 23]`, daily_target 1, theme `{hot = "#7c5cff", sun = "#ffd23f", font = "Bricolage Grotesque"}`, music `[]`, clips_per_video 3.
- `billikalesh`: pipeline `script`, voice `Kajal`, window `[9, 23]`, daily_target 1, theme `{hot = "#ff8a3d", sun = "#ffe066", font = "Poppins"}`, music `[]` (filled in Task 15), topics `"cats, dogs, wild animals and nature: one surprising fact or behaviour explained per reel"`.
- Sources `pexels` and `pixabay` for billikalesh, permission `{licence = "Pexels License"}` and `{licence = "Pixabay Content License"}`.
- `[api]`: `copyright_check = false`, `trial_reels = false`, `collaborators = false`, `follower_type_views = false`. Task 3 sets these from what the API actually does.

`config.load` validation:
- Every source's `page` exists.
- A `youtube_channel` source has `permission` keys `who`, `when`, `how`, `proof`.
- `window` lies within 0 to 24, and `daily_target` is 1 to 3.

`SCHEMA` holds the six tables from design §6.2. Times are ISO 8601 UTC text, and JSON blobs are text columns.
- `pages(handle pk, ig_user_id, token, token_expires_at, token_refreshed_at, paused_at, pause_reason, first_post_at, status_checked_at, recommendable)`
- `source_videos(id pk, source_id, page, video_id unique, url, title, published, status, note, created_at)`
- `clips(id pk, page, video_id, kind, start, end, moment, layer, script, credits, file_key, caption, status, reason, scheduled_at, container_id, media_id, permalink, trial, attempts default 0, created_at, published_at)`
- `insights(clip_id, due, fetched_at, views, reach, likes, comments, saves, shares, avg_watch_ms, pk(clip_id, due))`
- `account_daily(page, day, followers, views, views_non_follower, pk(page, day))`
- `events(id pk, page, at, kind, detail)`

`cli.py`: argparse with the subcommand `init` (connect, then insert one `pages` row per configured page). Later tasks add subcommands.

`static/privacy.html` and `static/data-deletion.html`:
- The app manages only Instagram accounts owned by Musubi.
- It stores API tokens, media ids and insights.
- Deletion: email developer@musubiclip.com, or remove the app under Instagram > Settings > Apps and websites. Data is deleted within 30 days.

- [ ] **Step 4: Run** `uv run pytest tests -q && uv run pages init`. Expected: PASS, and `~/MusubiPages/pages.db` exists with 2 page rows.

- [ ] **Step 5: Commit** `git add -A && git commit -m "Skeleton: config, database, storage, legal pages"`

### Task 2: Accounts and access (mostly [YOU]), plus `pages connect`

**Files:**
- Create: `pages/ig.py`, `pages/accounts.py`, `deploy/bucket.sh`
- Modify: `pages/cli.py` (add `connect`)
- Test: `tests/test_ig.py`, `tests/test_accounts.py`

**Interfaces:**
- Consumes: `db.connect`, `db.event`.
- Produces:
  - `ig.BASE = "https://graph.instagram.com/v26.0"`.
  - `class IGError(Exception)` with `code: int`, `subcode: int | None`, `message: str`.
  - `ig.get(path, token, **params) -> dict` and `ig.post(path, token, **params) -> dict` (form encoded, timeout 60). Both raise `IGError` from the Graph error body.
  - `ig.me(token) -> dict`, with fields `user_id,username,account_type,followers_count`.
  - `accounts.connect(db, handle, token, now) -> None`.

- [ ] **Step 1: Write the failing tests**

```python
def test_graph_error_carries_code_and_subcode(monkeypatch):
    fake_http_error(monkeypatch, 400, {"error": {"message": "spam", "code": 4, "error_subcode": 2207051}})
    with pytest.raises(ig.IGError) as e:
        ig.post("/1/media_publish", "tok", creation_id="9")
    assert (e.value.code, e.value.subcode) == (4, 2207051)

def test_connect_stores_token_for_the_matching_account(d, monkeypatch):
    monkeypatch.setattr(ig, "me", lambda t: {"user_id": "1789", "username": "billikalesh"})
    accounts.connect(d, "billikalesh", "tok", now=datetime(2026, 10, 23, tzinfo=UTC))
    row = d.execute("select * from pages where handle='billikalesh'").fetchone()
    assert (row["ig_user_id"], row["token"]) == ("1789", "tok")
    assert row["token_expires_at"] == "2026-12-22T00:00:00+00:00"

def test_connect_refuses_a_token_for_another_account(d, monkeypatch):
    monkeypatch.setattr(ig, "me", lambda t: {"user_id": "5", "username": "musubi_clip"})
    with pytest.raises(ValueError, match="token is for @musubi_clip, not @billikalesh"):
        accounts.connect(d, "billikalesh", "tok", now=datetime(2026, 10, 23, tzinfo=UTC))
```

- [ ] **Step 2: Run** `uv run pytest tests/test_ig.py tests/test_accounts.py -q`. Expected: FAIL.
- [ ] **Step 3: Implement** `ig.get/post/me` (stdlib `urllib`; on `HTTPError`, parse the JSON body into `IGError`) and `accounts.connect`. It checks the username, then stores the token with expiry `now + 60 days`. `pages connect <handle>` reads the token with `getpass`, so it never appears in shell history.
- [ ] **Step 4: Run** the tests. Expected: PASS. Commit: `git commit -am "Instagram client and pages connect"`
- [ ] **Step 5 [YOU]: AWS.**
  - In Billing > Credits, confirm the credits apply to **Amazon Bedrock**, and note the expiry date.
  - In the Bedrock console in `ap-south-1`, submit the Anthropic use case form if asked.
  - Create an AWS CLI profile `musubi-pages` on the Mac with admin rights for setup.
  - Then the agent runs `deploy/bucket.sh`. It creates the bucket `musubi-pages-<account id>` with Block Public Access on, SSE-S3, and lifecycle rules expiring `work/` and `footage/` after 30 days, and `clips/` and `backups/` after 90 days. The `clips/` rule is a backstop for rejected clips; `tick` deletes posted media at 30 days. It also creates an IAM user `musubi-pages-mac` limited to that bucket plus `polly:SynthesizeSpeech` and `polly:DescribeVoices`, with keys in a CLI profile `musubi-pages-mac`.
  - Done when `aws s3 ls s3://musubi-pages-<id> --profile musubi-pages-mac` works.
- [ ] **Step 6 [YOU]: Legal pages.** Upload `static/` to Cloudflare Pages: Workers & Pages > Create > Pages > Upload assets, project `musubi-pages-legal`. Done when `https://musubi-pages-legal.pages.dev/privacy.html` loads.
- [ ] **Step 7 [YOU]: Meta app.**
  - Create `podcastbawaal` if it doesn't exist yet (HANDOFF step 1).
  - In the Meta developer dashboard, create a **new Business app** (not 1074493771960727) with the Instagram product and Instagram Login.
  - Set the Privacy Policy URL and the data deletion instructions URL to the two Cloudflare Pages URLs.
  - Under Instagram > API setup with Instagram login, add `billikalesh` and `podcastbawaal`. Log in to each yourself in the popup, then accept any tester invite at instagram.com/accounts/manage_access > Tester invites.
  - Generate a token per account with the three scopes.
  - Run `uv run pages connect billikalesh` and `uv run pages connect podcastbawaal`, pasting each token.
  - Done when both `pages` rows have an `ig_user_id`.

### Task 3: Verify the Instagram unknowns before building on them

**Files:**
- Create: `pages/verify.py`, `research/verify-ig.md` (written from the output)
- Modify: `pages/ig.py`, `pages/cli.py` (add `verify-ig`), `pages.toml` (`[api]` flags)
- Test: `tests/test_verify.py`

**Interfaces:**
- Consumes: `ig.get/post`, `store.put/url`, `db.connect`.
- Produces:
  - `ig.publishing_limit(user_id, token) -> tuple[int, int]` (usage, total).
  - `ig.create_reel(user_id, token, video_url, caption, *, thumb_offset_ms: int, trial: bool, collaborators: list[str], ai_label: bool) -> str`. It sends `media_type=REELS`, `share_to_feed=true`, `is_ai_generated` when `ai_label` is set, `trial_params={"graduation_strategy":"SS_PERFORMANCE"}` when `trial` is set, and `collaborators` only when the list isn't empty. It returns the container id.
  - `ig.container(container_id, token) -> dict` (`status_code`, `copyright_check_status`).
  - `ig.wait_container(container_id, token, *, copyright: bool, every=30, limit=600) -> dict`. It polls until `status_code` is `FINISHED` and, when `copyright` is true, `copyright_check_status.status` is no longer `in_progress`. It raises `IGError` on `ERROR`, `EXPIRED` or the time limit.
  - `ig.account_views(user_id, token, since: date, until: date) -> dict` (`total`, `follower`, `non_follower`; the last two are `None` if the breakdown isn't returned).
  - `verify.run(db, handle) -> dict`, which **never publishes**.

- [ ] **Step 1: Write the failing tests**

```python
def test_verify_reports_each_unknown_and_never_publishes(d, monkeypatch):
    fake = FakeIG(container={"status_code": "FINISHED", "copyright_check_status": {"status": "completed", "matches_found": False}})
    fake.install(monkeypatch)           # replaces ig.* with recorders; ig.publish raises if called
    monkeypatch.setattr(store, "url", lambda k, s=3600: "https://example.test/" + k)
    out = verify.run(d, "billikalesh")
    assert out["publishing_limit"] == {"usage": 0, "total": 50}
    assert out["trial_params"] == "accepted" and out["ai_label"] == "accepted"
    assert out["copyright_check_status"] == {"status": "completed", "matches_found": False}
    assert "follower_type_views" in out and fake.published == []

def test_trial_params_rejection_is_reported_not_raised(d, monkeypatch):
    fake = FakeIG(reject_trial=True); fake.install(monkeypatch)
    monkeypatch.setattr(store, "url", lambda k, s=3600: "https://example.test/" + k)
    assert verify.run(d, "billikalesh")["trial_params"].startswith("rejected:")
```

- [ ] **Step 2: Run.** Expected: FAIL.
- [ ] **Step 3: Implement** the `ig` functions above and `verify.run`:
  1. Make a 5 second 1080×1920 30 fps test video with ffmpeg (`testsrc2` plus a `sine` AAC track; no third party content) and `store.put` it as `clips/verify-<timestamp>.mp4`.
  2. Read `publishing_limit`.
  3. Call `create_reel` with `trial=True, ai_label=True`. If the API rejects a parameter, retry without it and record `rejected: <message>`.
  4. Run `wait_container` with `copyright=True` and record `copyright_check_status`, or the error if the field is refused.
  5. Call `account_views` for the last 7 days and record whether the `follower_type` breakdown came back.
  6. If a source in `pages.toml` has `collab_ok = true`, create one more container with `collaborators=[source.instagram]` and record the result.

  Print the dict as JSON. `FakeIG` lives in `tests/conftest.py` and is reused by Task 6.
- [ ] **Step 4: Run** the tests. Expected: PASS. Commit: `git commit -am "API check for copyright, quota, trial reels, AI label"`
- [ ] **Step 5: Run it for real.** Run `PAGES_STORE=s3://musubi-pages-<id> AWS_PROFILE=musubi-pages-mac uv run pages verify-ig billikalesh`, then the same for `podcastbawaal`.
  - Write the results to `research/verify-ig.md` and set the `[api]` flags in `pages.toml` to match.
  - **Gate:** if `copyright_check_status` isn't available, set `copyright_check = false`. The checks from design §6.4 carry on unchanged: a permission record, no moments with music, and only the licensed bed. If `trial_params` is rejected, the first week goes out as normal reels. Tell Prateek either way.
  - Commit: `git commit -am "Record what the Instagram API does with our tokens"`

### Task 4: Claude and Polly (local first, Bedrock ready)

**Files:**
- Create: `pages/llm.py`, `pages/voice.py`
- Modify: `pages/cli.py` (add `check-aws`)
- Test: `tests/test_llm.py`, `tests/test_voice.py`

**Interfaces:**
- Produces:
  - `class LLMError(Exception)`.
  - `llm.ask(prompt: str, schema: type[M]) -> M`, with the backend read at call time from env `PAGES_LLM`:
    - `"claude-cli"` (the default) runs `claude -p <prompt> --json-schema <schema JSON> --output-format json --model opus --tools ""`, then validates `structured_output` with `schema`.
    - `"bedrock"` runs `AnthropicBedrockMantle(aws_region=env PAGES_BEDROCK_REGION or "ap-south-1").messages.parse(model="anthropic.claude-opus-5-5", max_tokens=16000, messages=[...], output_format=schema)` and returns `.parsed_output`.
  - `voice.speak(text: str, voice: str, out: Path) -> tuple[list[dict], float]`. It writes an mp3 (Polly `Engine="neural"`, `LanguageCode="en-IN"`) and returns the words as `[{"word","start","end"}]`, each word carrying the script's trailing punctuation, plus the length in seconds.

- [ ] **Step 1: Write the failing tests**

```python
class X(BaseModel):
    x: int

def test_cli_backend_validates_structured_output(monkeypatch):
    monkeypatch.setenv("PAGES_LLM", "claude-cli")
    seen = []
    monkeypatch.setattr(subprocess, "run", lambda cmd, **kw: (seen.append(cmd), subprocess.CompletedProcess(
        cmd, 0, json.dumps({"is_error": False, "structured_output": {"x": 2}}), ""))[1])
    assert llm.ask("give x", X).x == 2
    assert "--json-schema" in seen[0] and seen[0][seen[0].index("--model") + 1] == "opus"

def test_cli_error_raises(monkeypatch):
    monkeypatch.setenv("PAGES_LLM", "claude-cli")
    monkeypatch.setattr(subprocess, "run", lambda cmd, **kw: subprocess.CompletedProcess(cmd, 0, json.dumps({"is_error": True, "result": "limit"}), ""))
    with pytest.raises(llm.LLMError, match="limit"):
        llm.ask("x", X)

def test_bedrock_refusal_raises(monkeypatch):
    monkeypatch.setenv("PAGES_LLM", "bedrock")
    install_fake_mantle(monkeypatch, stop_reason="refusal")
    with pytest.raises(llm.LLMError, match="refus"):
        llm.ask("x", X)

def test_speak_keeps_punctuation_and_ends_each_word(monkeypatch, tmp_path):
    text = "Cats sleep 16h."
    marks = [{"time": 0, "type": "word", "start": 0, "end": 4, "value": "Cats"},
             {"time": 400, "type": "word", "start": 5, "end": 10, "value": "sleep"},
             {"time": 900, "type": "word", "start": 11, "end": 14, "value": "16h"}]
    install_fake_polly(monkeypatch, marks, seconds=1.6)
    words, seconds = voice.speak(text, "Kajal", tmp_path / "v.mp3")
    assert [w["word"] for w in words] == ["Cats", "sleep", "16h."]
    assert (words[0]["end"], words[-1]["end"], seconds) == (0.4, 1.6, 1.6)
```

- [ ] **Step 2: Run.** Expected: FAIL.
- [ ] **Step 3: Implement.**
  - Polly speech marks give `start` and `end` as byte offsets into the UTF-8 text. Extend each word over any punctuation that directly follows it. A word ends where the next one starts; the last ends at the audio length (`ffprobe`).
  - `pages check-aws` lists the `en-IN` voices and their engines, speaks "Testing one two" with the configured voice, and, if `PAGES_LLM=bedrock`, runs one `ask` that returns `{"ok": true}`.
- [ ] **Step 4: Run** the tests. Expected: PASS.
- [ ] **Step 5: Run the checks for real.**
  - `AWS_PROFILE=musubi-pages-mac uv run pages check-aws`: Polly works and `Kajal` lists `neural`.
  - `PAGES_LLM=bedrock AWS_PROFILE=musubi-pages uv run pages check-aws`: Bedrock answers from `ap-south-1`. If it says the model isn't served there, record the region that works in `research/verify-ig.md` and set `PAGES_BEDROCK_REGION`.
  - Commit: `git commit -am "Claude via CLI or Bedrock, Polly with word timings"`

---

## Phase 2: The posting spine (review, schedule, publish, measure)

### Task 5: Pick posting slots

**Files:**
- Create: `pages/schedule.py`
- Test: `tests/test_schedule.py`

**Interfaces:**
- Produces:
  - `IST = ZoneInfo("Asia/Kolkata")`.
  - `skipped_day(page: str, day: date) -> bool`: true when `int(sha256(f"{page}:{day}"))` is divisible by 9, which skips about one day in nine, on a different pattern per page.
  - `pick_slot(page: str, now: datetime, taken: list[datetime], window: tuple[int, int], daily_target: int, rng=random) -> datetime | None`, returned in UTC. It looks at most 14 days ahead.

- [ ] **Step 1: Write the failing tests**

```python
def at(day, h, m=0): return datetime(2026, 11, day, h, m, tzinfo=IST)

def test_slot_is_inside_the_ist_window_and_after_now():
    now = datetime(2026, 11, 2, 1, 0, tzinfo=UTC)          # 06:30 IST
    for seed in range(50):
        slot = pick_slot("billikalesh", now, [], (9, 23), 1, random.Random(seed))
        assert 9 <= slot.astimezone(IST).hour < 23 and slot >= now + timedelta(minutes=10)

def test_three_hours_apart_and_daily_target():
    taken = [at(2, 12)]
    two = pick_slot("x", at(2, 8), taken, (9, 23), 2, random.Random(1))
    assert abs(two - taken[0]) >= timedelta(hours=3)
    one = pick_slot("x", at(2, 8), taken, (9, 23), 1, random.Random(1))
    assert one.astimezone(IST).date() > date(2026, 11, 2)

def test_skipped_days_are_occasional_differ_by_page_and_get_no_post():
    days = [date(2026, 11, 1) + timedelta(n) for n in range(90)]
    a = {d for d in days if skipped_day("podcastbawaal", d)}
    assert 4 <= len(a) <= 20 and a != {d for d in days if skipped_day("billikalesh", d)}
    first = min(a)
    slot = pick_slot("podcastbawaal", datetime.combine(first, time(0), IST), [], (9, 23), 1, random.Random(3))
    assert slot.astimezone(IST).date() != first
```

- [ ] **Step 2: Run.** Expected: FAIL.
- [ ] **Step 3: Implement.** Go day by day from today (IST) and skip any day that is skipped or already at its target. On each day, try 50 random minutes inside the window, keeping only times at least 10 minutes from now and at least 3 hours from every `taken` time. Return the first that fits.
- [ ] **Step 4: Run.** Expected: PASS. Commit: `git commit -am "Posting slots"`

### Task 6: Publisher

**Files:**
- Create: `pages/publish.py`
- Modify: `pages/ig.py` (`publish`, `media`), `pages/accounts.py` (`pause`, `unpause`)
- Test: `tests/test_publish.py`

**Interfaces:**
- Consumes:
  - `ig.create_reel`, `ig.wait_container`, `ig.publishing_limit`, `ig.IGError` (Task 3).
  - `schedule.pick_slot` (Task 5), `store.url`, `cfg.api` flags.
- Produces:
  - `ig.publish(user_id, token, container_id) -> str` (the media id) and `ig.media(media_id, token) -> dict` (permalink).
  - `accounts.pause(db, handle, reason, now)`: sets `paused_at` and `pause_reason`, moves the page's `scheduled` clips back to `approved` with `scheduled_at = NULL`, and records an event `paused`. `accounts.unpause(db, handle, now)` clears the pause and records `unpaused`.
  - `publish.schedule_approved(db, cfg, now, rng=random)`: gives each `approved` clip of a connected, unpaused page a slot. `taken` is the page's published and scheduled times.
  - `publish.publish_due(db, cfg, now)`: publishes `scheduled` clips whose time has come.
  - `PAUSE_SUBCODES = {2207050, 2207051}` and `TOKEN_CODES = {190}`.

- [ ] **Step 1: Write the failing tests** (`FakeIG` from conftest; `store.url` patched to return an `https://` URL; clip rows inserted by the helper `add_clip(d, page, status, scheduled_at=...)`):

```python
def test_first_week_goes_out_as_a_trial_reel_with_the_ai_label(d, cfg, fake_ig): ...
    # assert fake_ig.created[0]["trial"] is True and fake_ig.created[0]["ai_label"] is True
    # assert clip status 'published', media_id set, permalink set, pages.first_post_at == now
def test_after_seven_days_reels_are_not_trial(d, cfg, fake_ig): ...
def test_spam_error_pauses_the_page_and_unschedules_its_clips(d, cfg, fake_ig):
    fake_ig.fail_create = ig.IGError(4, 2207051, "spam")
    # two scheduled clips due now → after publish_due: pages.paused_at set, pause_reason contains "2207051",
    # both clips status 'approved' with scheduled_at NULL, one 'paused' event
def test_other_errors_retry_twice_then_fail(d, cfg, fake_ig):
    fake_ig.fail_create = ig.IGError(2, None, "temporary")
    # three publish_due runs (now advanced past each retry) → attempts 3, status 'failed', reason "temporary"
def test_copyright_match_fails_the_clip_without_pausing(d, cfg, fake_ig):
    fake_ig.container = {"status_code": "FINISHED", "copyright_check_status": {"status": "completed", "matches_found": True}}
    # with cfg.api["copyright_check"] True → status 'failed', reason "copyright match", page not paused, ig.publish not called
def test_full_quota_waits(d, cfg, fake_ig):
    fake_ig.limit = (50, 50)   # → nothing created, clip still 'scheduled'
def test_paused_page_publishes_nothing(d, cfg, fake_ig): ...
def test_expired_token_keeps_clips_and_asks_for_reconnect(d, cfg, fake_ig):          # Review Focus 1
    fake_ig.fail_create = ig.IGError(190, None, "Error validating access token")
    # → clip still 'scheduled', attempts unchanged, event 'token_invalid',
    #   pages.token_expires_at == now (so the review page shows "reconnect"), no clip 'failed'
def test_unpause_gives_fresh_slots_not_a_burst(d, cfg, fake_ig):                      # Review Focus 2
    # schedule two clips, pause, unpause 5 days later, schedule_approved(now) →
    # every scheduled_at > now and they are ≥ 3 h apart; publish_due(now) publishes nothing
```

- [ ] **Step 2: Run.** Expected: FAIL.
- [ ] **Step 3: Implement.** In `publish_due`, for each due clip whose page is connected and unpaused:
  1. Check the quota and wait if it's full.
  2. Get `url = store.url(file_key, 6 * 3600)` and refuse anything that isn't `https://`.
  3. `trial = cfg.api["trial_reels"] and (first_post_at is None or now < first_post_at + 7 days)`.
  4. Add `collaborators=[source.instagram]` when `cfg.api["collaborators"]` is set and the source has `collab_ok`.
  5. Call `create_reel` with `thumb_offset_ms=1300` (the hook is fully drawn by 1.3 s) and `ai_label=True`.
  6. Run `wait_container` with `copyright=cfg.api["copyright_check"]`.
  7. Publish, then store `media_id`, `permalink` and `published_at`, and set `first_post_at` if it's empty.

  Error handling:
  - A subcode in `PAUSE_SUBCODES` calls `accounts.pause`.
  - A code in `TOKEN_CODES` records `token_invalid` and sets `token_expires_at = now`.
  - Anything else adds one to `attempts`. Under 3, push `scheduled_at` back 15 minutes; at 3, mark the clip `failed` with the message.
- [ ] **Step 4: Run.** Expected: PASS. Commit: `git commit -am "Publisher with pause, retries, trial week, AI label"`

### Task 7: Review page

**Files:**
- Create: `pages/web.py`, `pages/templates/review.html`
- Modify: `pages/cli.py` (add `web`)
- Test: `tests/test_web.py`

**Interfaces:**
- Consumes: `accounts.unpause`, `store.url`, `db`, `cfg`, `clips_pipeline.add_link` (Task 11; until then the link form returns 501).
- Produces: the FastAPI `app` with these routes:
  - `GET /`: per page, its status (connected, token warning, paused with reason, last account status check), drafts, and a count of approved and scheduled clips.
  - Each draft shows its video (`store.url`), hook, layer text or script claims, restricted topic flags, footage credits, an editable caption, and the source with its permission summary and Instagram profile link.
  - `POST /clips/{id}/approve` (form `caption`) and `POST /clips/{id}/reject` (form `reason`, required).
  - `POST /pages/{handle}/unpause`.
  - `POST /pages/{handle}/status` (form `recommendable` = yes|no) records the weekly Account Status check. A "no" also runs `accounts.pause(..., "not recommendable")` (design §6.5).
  - `POST /links` (form `url`, `page`, `note`).
  - `GET /files/{key:path}`: only when the store is local.
  - Access check: when env `CF_ACCESS_AUD` is set, every request needs a valid `Cf-Access-Jwt-Assertion`, verified with `PyJWKClient(f"https://{CF_ACCESS_TEAM}/cdn-cgi/access/certs")` for audience `CF_ACCESS_AUD`, with an `email` ending in `@musubiclip.com`. Otherwise it returns 403.
  - `pages web` serves on `127.0.0.1:8000`.

- [ ] **Step 1: Write the failing tests**

```python
def test_review_shows_a_draft_with_its_permission_and_flags(client, d): ...
    # insert draft with layer flags ["health claim"] for a source with permission who="Host Name"
    # → 200 and body contains hook text, caption, "Host Name", "health claim"
def test_approve_saves_the_edited_caption(client, d): ...   # → status 'approved', caption == "edited"
def test_reject_needs_a_reason(client, d): ...              # empty → 400; "off topic" → 'rejected', reason saved
def test_token_warning_ten_days_before_expiry(client, d): ... # expires in 9 days → "reconnect" shown; 11 days → not
def test_not_recommendable_pauses_the_page(client, d): ...    # recommendable=no → paused_at set, reason "not recommendable"
def test_access_required_when_configured(monkeypatch, d):
    monkeypatch.setenv("CF_ACCESS_AUD", "aud"); monkeypatch.setenv("CF_ACCESS_TEAM", "musubi.cloudflareaccess.com")
    assert TestClient(web.app).get("/").status_code == 403
def test_access_allows_only_musubiclip_emails(monkeypatch, d):
    # sign JWTs with a test RSA key, patch PyJWKClient to return it
    # a@gmail.com → 403; prateek@musubiclip.com → 200
```

- [ ] **Step 2: Run.** Expected: FAIL.
- [ ] **Step 3: Implement.** One Jinja template with plain HTML and a few lines of CSS: a 9:16 video at 270 px wide next to its text, and one column at phone width. No JS framework.
- [ ] **Step 4: Run** `uv run pytest tests/test_web.py -q`, then `uv run pages web` and open http://127.0.0.1:8000. Expected: both pages listed and connected, with an empty queue.
- [ ] **Step 5: Commit** `git commit -am "Review page"`

### Task 8: Tick (insights, metrics, tokens, backups, media cleanup)

**Files:**
- Create: `pages/insights.py`, `pages/tick.py`
- Modify: `pages/ig.py` (`media_insights`, `refresh`), `pages/accounts.py` (`refresh_tokens`), `pages/cli.py` (add `tick`), `pages/templates/review.html` (metrics row)
- Test: `tests/test_tick.py`

**Interfaces:**
- Consumes: `publish.schedule_approved`, `publish.publish_due`, `ig.me`, `ig.account_views`.
- Produces:
  - `ig.media_insights(media_id, token) -> dict[str, int]` for `views,reach,likes,comments,saved,shares,ig_reels_avg_watch_time`. An empty set comes back as zeros.
  - `ig.refresh(token) -> tuple[str, int]`, calling `GET /refresh_access_token?grant_type=ig_refresh_token`.
  - `insights.DUE = {"1h": 1h, "24h": 24h, "72h": 72h, "7d": 7d}` (timedeltas).
  - `insights.fetch_due(db, now)`, `insights.daily_account(db, cfg, now)` (once per IST day: `followers_count` and yesterday's views with the follower split when `cfg.api["follower_type_views"]`), and `insights.page_metrics(db, page, now) -> dict(reels, median_views, non_follower_share)` (reels published in the last 28 days).
  - `accounts.refresh_tokens(db, now)`: refreshes when `token_refreshed_at` (or connect time) is at least 7 days old.
  - `tick.tick(db, cfg, now)`: runs schedule, publish, insights, daily account, refresh, backup and media cleanup in that order. A failure in one step is recorded as an event and the rest still run.

- [ ] **Step 1: Write the failing tests**

```python
def test_insights_fetched_once_at_each_point(d, fake_ig): ...
    # published at T; tick at T+2h → only "1h" row; T+25h → "24h" added; again at T+25h → no new call
def test_page_metrics_median_and_non_follower_share(d): ...
    # 7d views 100, 300, 5000 → median 300; account_daily views 1000 with non_follower 800 → share 0.8
def test_refresh_is_weekly_and_records_the_new_expiry(d, fake_ig): ...
    # refreshed 6 days ago → no call; 8 days ago → token replaced, token_expires_at == now + expires_in
def test_backup_once_per_day(d, local_store): ...
    # two ticks the same IST day → one "backups/pages-2026-11-02.db" key
def test_media_deleted_thirty_days_after_posting(d, local_store): ...
    # published 31 days ago → file gone, file_key NULL; 29 days ago → kept
def test_one_failing_step_does_not_stop_the_others(d, monkeypatch): ...
```

- [ ] **Step 2: Run.** Expected: FAIL.
- [ ] **Step 3: Implement.** Backups use `sqlite3.Connection.backup` into a temp file and then `store.put`. The review page shows `page_metrics` under each page, and a "check Account Status" reminder when `status_checked_at` is older than 7 days.
- [ ] **Step 4: Run.** Expected: PASS. Then `uv run pages tick`, which exits 0 with nothing to do.
- [ ] **Step 5: Commit** `git commit -am "Tick: insights, metrics, token refresh, backups, cleanup"`

---

## Phase 3: Clip pipeline (podcastbawaal)

### Task 9: Vendor the engine and give it a server mode, `render_one`, and page themes

**Files:**
- Create: `engine/__init__.py`, `engine/clipper.py`, `engine/assets/` and `engine/test_clipper.py` (copied from `~/.claude/skills/musubi-clips`)
- Test: `engine/test_clipper.py`

**Interfaces:**
- Produces:
  - `SKILL_DIR = Path(__file__).resolve().parent`.
  - Env `MUSUBI_CLIPS_OFFLINE=1` (read at call time): `find_stream` returns `None` and `video_section` raises `RuntimeError("no section covers <start>-<end>")` instead of calling yt-dlp.
  - `frame_filter(src_w, src_h, crop_w, crop_h, steps, faces_seen: list[bool]) -> str`: the frame choice pulled out of `cut_graph`. A wide source is always cropped to the full 9:16. The engine's blurred background fallback for shots with no face is removed, because design §6.3 says never letterboxed.
  - `SECTION_PAD = 8.0`, so sections fetched before the layer exists cover a pre-roll of up to 7 seconds.
  - `reel_page(reel: dict, design: str, total: float, duration: float, music_tag: str, theme: dict | None) -> str`: the template fill pulled out of `render_styled`. A theme sets `--hot`, `--sun` and `--display` and adds an `@font-face` for Poppins.
  - `render_one(workdir: Path, moment: dict, out: Path, *, theme: dict | None = None, intro: dict | None = None, outro: dict | None = None, music: Path | None = None) -> Path`: renders one moment with v2, no watermark and no end screen. `intro` and `outro` are wired in Task 10.

- [ ] **Step 1: Copy the engine.** Run `cp ~/.claude/skills/musubi-clips/scripts/{clipper.py,test_clipper.py} engine/ && cp -R ~/.claude/skills/musubi-clips/assets engine/`. Change the test import to `from engine.clipper import ...` and fix `SKILL_DIR`. Run `uv run pytest engine -q`. Expected: the existing 17 tests PASS.
- [ ] **Step 2: Write the failing tests**

```python
def test_offline_never_calls_youtube(tmp_path, monkeypatch):
    monkeypatch.setenv("MUSUBI_CLIPS_OFFLINE", "1")
    monkeypatch.setattr(clipper, "run", lambda *a, **k: pytest.fail("called " + a[0][0]))
    assert clipper.find_stream(tmp_path, {"url": "https://youtu.be/x"}) is None
    with pytest.raises(RuntimeError, match="no section covers"):
        clipper.video_section(tmp_path, {"url": "https://youtu.be/x"}, {"start": 10, "end": 40, "cold_open": None}, None)

def test_faceless_wide_shots_are_cropped_not_letterboxed():
    f = clipper.frame_filter(1920, 1080, 608, 1080, [(0, 656)], [False, False, False])
    assert f.startswith("crop=608:1080") and "boxblur" not in f

def test_theme_sets_colours_and_font():
    html = clipper.reel_page({"duration": 30}, "v2", 30, 30, "", {"hot": "#7c5cff", "sun": "#ffd23f", "font": "Poppins"})
    assert "--hot: #7c5cff" in html and "--display: \"Poppins\"" in html and "Poppins-ExtraBold.ttf" in html

@pytest.mark.slow
def test_render_one_makes_a_vertical_reel(fixture_workdir, tmp_path):
    # fixture: 60 s ffmpeg testsrc2 1920x1080 + sine section, transcript.json of synthetic words
    out = clipper.render_one(fixture_workdir, MOMENT_30S, tmp_path / "r.mp4", theme=THEME)
    assert clipper.probe_size(out) == (1080, 1920) and 29 < clipper.duration_of(out) < 32
```

- [ ] **Step 3: Run.** Expected: FAIL on the new tests.
- [ ] **Step 4: Implement.** `render_one` reuses `tidy_clips([moment], words, 1)`, `english_words`, `video_section`, `shifted` and `render_styled`, writing to `out`. Leave the CLI and `render_all` working as before.
- [ ] **Step 5: Run** `uv run pytest engine -q -m "slow or not slow"`. Expected: PASS. Commit: `git commit -am "Engine: vendored, offline mode, render_one, page themes"`

### Task 10: Engine original layer (voiceover intro, takeaway, context cards)

**Files:**
- Modify: `engine/clipper.py`, `engine/assets/reel/v2.html`
- Test: `engine/test_clipper.py`

**Interfaces:**
- Consumes: `render_one` (Task 9).
- Produces:
  - `intro = {"audio": Path, "seconds": float}`: a pre-roll of `seconds` from just before the moment, with the source audio at 12% and the voiceover at full volume. The hook stays on screen until `seconds` (not 1.85), there are no captions during the pre-roll, and any cold open is ignored.
  - `outro = {"audio": Path, "seconds": float, "text": str}`: the last frame is held for `seconds` while a takeaway card shows `text` over the voiceover.
  - `moment["cards"] = [{"at": <source seconds>, "title": str, "body": str, "hold": 4}]` (1 to 3): context cards in the theme's colours, placed in the band clear of the face, like the stat card.
  - `reel_data` adds `intro: {"seconds"}`, `outro: {"at", "seconds", "text"}` and `cards: [{"at" in reel seconds, ...}]`.
  - `pieces_for(clip)` puts `(start - intro, start)` first when `clip["intro"]` is set.

- [ ] **Step 1: Write the failing tests**

```python
def test_intro_moves_captions_after_the_voiceover():
    clip = {**tidied(100.0, 140.0), "intro": 4.0}
    assert clipper.pieces_for(clip)[0] == (clip["start"] - 4.0, clip["start"])
    data = clipper.reel_data(clip, WORDS_95_TO_141, duration=44.0)
    assert data["intro"] == {"seconds": 4.0} and min(w["s"] for w in data["words"]) >= 4.0

def test_cards_land_in_reel_time_after_the_intro():
    clip = {**tidied(100.0, 140.0), "intro": 4.0, "cards": [{"at": 110.0, "title": "Who", "body": "Ex ISRO", "hold": 4}]}
    card = clipper.reel_data(clip, WORDS_95_TO_141, duration=44.0)["cards"][0]
    assert card["at"] == round(4.0 + 110.0 - clip["start"], 3) and card["title"] == "Who"

def test_outro_starts_when_the_moment_ends():
    clip = {**tidied(100.0, 140.0), "intro": 4.0, "outro": {"seconds": 3.0, "text": "Save this"}}
    out = clipper.reel_data(clip, WORDS_95_TO_141, duration=47.0)["outro"]
    assert out == {"at": round(4.0 + clip["end"] - clip["start"], 3), "seconds": 3.0, "text": "Save this"}

@pytest.mark.slow
def test_render_one_with_the_layer_is_intro_plus_clip_plus_outro(fixture_workdir, tmp_path, vo_4s, vo_3s):
    out = clipper.render_one(fixture_workdir, {**MOMENT_30S, "cards": CARDS}, tmp_path / "r.mp4", theme=THEME,
                             intro={"audio": vo_4s, "seconds": 4.0}, outro={"audio": vo_3s, "seconds": 3.0, "text": "Save this"})
    assert 36.5 < clipper.duration_of(out) < 38.5
```

- [ ] **Step 2: Run.** Expected: FAIL.
- [ ] **Step 3: Implement.**
  - The pre-roll is a piece with a `volume=0.12` audio filter, and `clip_timeline` skips its words.
  - The outro is `tpad=stop_mode=clone` on the video and `apad` on the audio in `cut_graph`.
  - The voiceovers are `<audio>` tracks in the HyperFrames page at `data-start` 0 and at `outro.at`, the same mechanism as the music track.
  - In `v2.html`: hook end = `max(1.85, intro.seconds)`, a `#ctx` card and a `#takeaway` card.
- [ ] **Step 4: Run** `uv run pytest engine -q -m "slow or not slow"`, then `uv run python -m engine.clipper check <workdir>` on the slow test's output. Look at the contact sheet: the hook shows during the intro, the cards sit clear of the face, and the takeaway is readable.
- [ ] **Step 5: Commit** `git commit -am "Engine: voiceover intro, takeaway and context cards"`

### Task 11: Mac fetcher, jobs, intake and links

**Files:**
- Create: `pages/fetcher.py`, `pages/clips_pipeline.py`, `deploy/com.musubi.pages-fetcher.plist`
- Modify: `pages/cli.py` (add `fetch`, `work`), `pages/web.py` (wire `/links`)
- Test: `tests/test_fetcher.py`, `tests/test_clips_pipeline.py`

**Interfaces:**
- Consumes: `store.*`, `engine.clipper.prepare` and `fetch_sections` (run in the local `MUSUBI_CLIPS_DIR`), `config.Source`.
- Produces:
  - Store protocol:
    - `jobs/fetch.json` = `{"watch": [{"source", "url"}], "prepare": [{"video_id", "url"}], "sections": [{"video_id", "url", "count"}], "cc_search": []}`.
    - `inbox/<source_id>.json` = the latest 15 uploads, `[{"video_id", "url", "title", "published"}]`.
    - `work/<video_id>/` holds `meta.json`, `transcript.json`, `transcript.txt`, `source-audio.info.json`, `captions.*.json3`, `moments.json`, `english.json`, `sections/*.mp4`, `sections.done` and `error.txt`.
  - `fetcher.run_jobs() -> dict` (counts done), run as `pages fetch`.
  - `clips_pipeline.queue_size(db, page) -> int` (clips `planned`, `draft`, `approved` or `scheduled`); `QUEUE_LOW = 7`.
  - `clips_pipeline.write_jobs(db, cfg)` and `clips_pipeline.take_inbox(db, cfg)`.
  - `clips_pipeline.add_link(db, cfg, url, page, note) -> int` (raises `ValueError`).
  - `clips_pipeline.belongs(info: dict, source_url: str) -> bool`.
  - `clips_pipeline.advance(db, cfg)`: `new` → `prepared`/`skipped`, and `picked` → `fetched`.

- [ ] **Step 1: Write the failing tests.** `conftest.py` gains:
  - `cfg_with_podcast`: the pilot config plus one `youtube_channel` source `pod` for podcastbawaal, with a full permission record.
  - `put_prepared(store, video_id, info)`: writes the files a prepare leaves in `work/<id>/`.

  Tasks 12 and 13 build `prepared_video`, `prepared_hindi_video` and `fetched_video` on these.

```python
def test_jobs_watch_only_while_the_queue_is_low(d, cfg_with_podcast, local_store): ...
    # queue 0 → watch has the source; queue 7 → watch empty
def test_jobs_list_new_videos_to_prepare_and_picked_to_fetch(d, cfg_with_podcast, local_store): ...
def test_inbox_adds_only_unseen_videos_after_since(d, cfg_with_podcast, local_store): ...
def test_fetcher_skips_work_already_in_the_store(local_store, monkeypatch):                 # Review Focus 3
    # transcript.json already in store → clipper.prepare not called; sections.done present → fetch_sections not called;
    # running run_jobs twice uploads nothing the second time
def test_link_from_unlisted_channel_is_skipped_without_a_note(d, cfg_with_podcast, local_store):   # Review Focus 4
    vid = clips_pipeline.add_link(d, cfg_with_podcast, "https://www.youtube.com/watch?v=abc", "podcastbawaal", "")
    put_prepared(local_store, "abc", info={"channel_url": "https://www.youtube.com/channel/UCother", "uploader_url": "https://www.youtube.com/@other"})
    clips_pipeline.advance(d, cfg_with_podcast)
    row = d.execute("select status, note from source_videos where id=?", (vid,)).fetchone()
    assert row["status"] == "skipped" and "not an allowed source" in row["note"]
    # same with note "one off: host emailed 25 Oct" → status 'prepared'
def test_a_video_belongs_to_one_page_only(d, cfg_with_podcast, local_store):                 # Review Focus 5
    clips_pipeline.add_link(d, cfg_with_podcast, "https://youtu.be/abc", "podcastbawaal", "")
    with pytest.raises(ValueError, match="already used by podcastbawaal"):
        clips_pipeline.add_link(d, cfg_with_podcast, "https://www.youtube.com/watch?v=abc", "billikalesh", "note")
def test_belongs_matches_handle_or_channel_url():
    assert clips_pipeline.belongs({"uploader_url": "https://www.youtube.com/@Pod"}, "https://www.youtube.com/@pod/")
```

- [ ] **Step 2: Run.** Expected: FAIL.
- [ ] **Step 3: Implement.**
  - Watch: `yt-dlp --flat-playlist -J --playlist-end 15 <url>/videos`.
  - Prepare: `clipper.prepare(url)`, then upload the files listed above. If the engine exits because there are no captions, upload `error.txt`.
  - Sections: download `moments.json`, run `clipper.fetch_sections(workdir, count)`, upload `sections/*.mp4`, then `sections.done`.
  - Each job first checks its output key and skips if it's there.
  - The plist runs `pages fetch` every 30 minutes with `PAGES_STORE` and `AWS_PROFILE=musubi-pages-mac` set.
- [ ] **Step 4: Run.** Expected: PASS.
- [ ] **Step 5 [YOU]:** add the 2 or 3 podcasts that gave written permission to `pages.toml` as `youtube_channel` sources: url, instagram, `permission = {who, when, how, proof, collab_ok}`, and `since`. Then the agent runs `uv run pages work` (jobs only for now) and `uv run pages fetch`. Expected: `inbox/` and `work/<id>/transcript.json` appear in the local store.
- [ ] **Step 6: Commit** `git commit -am "Mac fetcher, jobs, intake, pasted links"`

### Task 12: Pick moments

**Files:**
- Create: `pages/writing.py`
- Modify: `pages/clips_pipeline.py` (`music_spans`, `pick`)
- Test: `tests/test_writing.py`, `tests/test_clips_pipeline.py`

**Interfaces:**
- Consumes: `llm.ask`, `engine.clipper` (`moment_problems`, `tidy_clips`, `all_words`, `untranslated`), `store`.
- Produces:
  - `writing.Moment` (pydantic): the engine's moment fields `start, end, title, hook_text, hook_parts, reason, emphasis, focus_x, speaker_name, speaker_role, hook, standalone, payoff, emotion`. No `stat`, `deal` or cold open.
  - `writing.pick_moments(transcript: str, title: str, want: int) -> list[Moment]`. The prompt carries the musubi-clips picking rules (`engine/SKILL.md` §2), 30 to 90 seconds, and "skip any span with music".
  - `writing.translate(sentences: list[str]) -> list[dict]` (`[{"start","end","text"}]`).
  - `clips_pipeline.music_spans(json3_text: str) -> list[tuple[float, float]]`: events whose text has `[Music]`, `[संगीत]` or `♪`, spanning `tStartMs` to `tStartMs + dDurationMs`.
  - `clips_pipeline.pick(db, cfg, video_row)`:
    1. Ask for `2 × clips_per_video` moments.
    2. Drop those with `moment_problems`, those outside 30 to 90 s, and those overlapping music.
    3. Keep the top `clips_per_video` by `tidy_clips`.
    4. Write `moments.json`, plus `english.json` when the language isn't `en`.
    5. Insert `clips` rows (`planned`, `kind="clip"`, `moment` JSON) and set the video to `picked`.
    6. If none survive, the video is `skipped` with the note "no usable moments".

- [ ] **Step 1: Write the failing tests**

```python
def test_music_spans_reads_caption_tags():
    j = json.dumps({"events": [{"tStartMs": 1000, "dDurationMs": 4000, "segs": [{"utf8": "[Music]"}]},
                               {"tStartMs": 6000, "dDurationMs": 2000, "segs": [{"utf8": "hello"}]}]})
    assert clips_pipeline.music_spans(j) == [(1.0, 5.0)]

def test_pick_drops_music_short_and_broken_moments(d, cfg_with_podcast, prepared_video, monkeypatch):
    monkeypatch.setattr(writing, "pick_moments", lambda *a: [M(100, 150), M(10, 40), M(300, 310), M(400, 470, hook=None)])
    # music span (20, 30) in captions → keeps only 100-150; one planned clip; moments.json in store
def test_pick_with_nothing_usable_skips_the_video(...): ...
def test_hindi_video_gets_english_lines(d, cfg_with_podcast, prepared_hindi_video, monkeypatch): ...
    # language "hi" → writing.translate called with the untranslated sentences; english.json in store
```

- [ ] **Step 2: Run.** Expected: FAIL.
- [ ] **Step 3: Implement.** Copy `SKILL.md` to `engine/SKILL.md` for the prompt text. `step()` in `clips_pipeline` now runs, in order: `write_jobs`, `take_inbox`, `advance`, then `pick` for one prepared video.
- [ ] **Step 4: Run.** Expected: PASS. Then for real: `uv run pages work` picks moments for the video from Task 11 through `claude -p`. Read `moments.json` and check the picks.
- [ ] **Step 5: Commit** `git commit -am "Pick moments with Claude, drop music, translate"`

### Task 13: Make clips (layer, voice, render, caption) and drafts

**Files:**
- Modify: `pages/writing.py` (`Layer`, `write_layer`, `write_caption`), `pages/clips_pipeline.py` (`make_clips`)
- Test: `tests/test_writing.py`, `tests/test_clips_pipeline.py`

**Interfaces:**
- Consumes: `voice.speak`, `clipper.render_one` (Tasks 9 and 10), `store`, `writing.Moment`.
- Produces:
  - `writing.Card(at: float, title: str, body: str)`.
  - `writing.Layer(intro: str, takeaway: str, cards: list[Card], flags: list[str])`. The prompt asks for an intro of 8 to 16 words and a takeaway of 6 to 10 words, in the page's voice; 1 to 3 cards with facts the clip doesn't say, each `at` inside the moment; and flags for restricted topics: health claims, cosmetic procedures, get rich schemes, miracle or astrology claims.
  - `writing.write_layer(page, moment, text) -> Layer`.
  - `writing.write_caption(page, about: str, credits: list[str], previous: list[str]) -> str`. It returns the body with keywords, then credit lines, then at most 5 hashtags, at most 2200 characters, and never equal to anything in `previous` (one retry, then `LLMError`).
  - `clips_pipeline.make_clips(db, cfg, video_row)`. For each `planned` clip:
    1. Layer, then voice the intro and the takeaway. An intro over 7 s or a takeaway over 5 s fails the clip with "layer too long".
    2. `render_one(..., theme=page.theme, intro, outro, music=None)` with `MUSUBI_CLIPS_OFFLINE=1`.
    3. `store.put("clips/<id>.mp4")`.
    4. Caption, with the credit `🎙️ <video title>` plus `via @<source.instagram>` when set.
    5. The clip becomes `draft`.

    Any exception fails just that clip with its message. The video becomes `cut`. `step()` runs at most one `make_clips` per call.

- [ ] **Step 1: Write the failing tests**

```python
def test_caption_caps_hashtags_and_appends_credits(monkeypatch):
    monkeypatch.setattr(llm, "ask", lambda p, s: s(text="Why founders burn out", hashtags=["a", "#b", "c", "d", "e", "f", "g"]))
    cap = writing.write_caption(PAGE, "burnout clip", ["🎙️ Ep 12 via @pod"], previous=[])
    assert cap.count("#") == 5 and "🎙️ Ep 12 via @pod" in cap and len(cap) <= 2200

def test_caption_never_repeats(monkeypatch): ...   # ask returns the previous text twice → LLMError

def test_make_clips_turns_planned_into_drafts(d, cfg_with_podcast, fetched_video, monkeypatch):
    # writing.write_layer, voice.speak (4 s / 3 s), clipper.render_one (writes a dummy mp4), writing.write_caption patched
    # → clip 'draft', file_key "clips/<id>.mp4" exists in store, layer JSON has the cards, render_one got theme + intro + outro
def test_long_intro_fails_only_that_clip(d, cfg_with_podcast, fetched_video, monkeypatch): ...  # speak → 8 s → 'failed', "layer too long"
```

- [ ] **Step 2: Run.** Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run.** Expected: PASS. Then for real: `uv run pages fetch` (sections), `uv run pages work` (render), and `uv run pages web`. Expected: podcastbawaal drafts on the review page. Watch each one with sound.
- [ ] **Step 5: Commit** `git commit -am "Clip pipeline: layer, voice, render, caption"`

---

## Phase 4: Script first pipeline (billikalesh)

### Task 14: Script and footage search

**Files:**
- Create: `pages/script_pipeline.py`
- Modify: `pages/writing.py` (`Beat`, `Script`, `write_script`)
- Test: `tests/test_script_pipeline.py`, `tests/test_writing.py`

**Interfaces:**
- Consumes: `llm.ask`; env `PEXELS_KEY` and `PIXABAY_KEY`.
- Produces:
  - `writing.Beat(line: str, shot_query: str)`.
  - `writing.Script(idea, title, hook_text, beats: list[Beat], claims: list[str], flags: list[str])`: 5 to 7 beats, where the first is the hook line and the last the closing line, 20 to 45 seconds when spoken, `hook_text` at most 8 words, every factual claim listed in `claims`.
  - `writing.write_script(page, used_ideas: list[str]) -> Script` (raises `ValueError` on beats outside 5 to 7 or a hook over 8 words).
  - `script_pipeline.Shot` (dataclass): `provider`, `id`, `download_url`, `page_url`, `author`, `licence`, `seconds`.
  - `script_pipeline.search_footage(query: str, seconds: float, used: set[str]) -> Shot | None`. It tries Pexels (`/videos/search`, `orientation=portrait`) and then Pixabay (`/api/videos/`, `safesearch=true`), taking the first video at least `seconds` long whose `f"{provider}:{id}"` isn't in `used`.

- [ ] **Step 1: Write the failing tests**

```python
def test_script_prompt_lists_used_ideas_and_validates_beats(monkeypatch):
    seen = {}
    monkeypatch.setattr(llm, "ask", lambda p, s: (seen.setdefault("p", p), SCRIPT_WITH_4_BEATS)[1])
    with pytest.raises(ValueError, match="5 to 7 beats"):
        writing.write_script(BILLI, ["why cats knead"])
    assert "why cats knead" in seen["p"]

def test_footage_prefers_pexels_skips_used_and_short(monkeypatch):
    fake_http_json(monkeypatch, pexels=[vid(1, 3), vid(2, 9), vid(3, 9)], pixabay=[])
    shot = script_pipeline.search_footage("cat stretching", 6.0, used={"pexels:2"})
    assert (shot.provider, shot.id, shot.licence) == ("pexels", "3", "Pexels License")

def test_footage_falls_back_to_pixabay_then_none(monkeypatch): ...
```

- [ ] **Step 2: Run.** Expected: FAIL.
- [ ] **Step 3 [YOU]:** create free Pexels and Pixabay API keys and put them in `~/.config/musubi-pages.env` as `PEXELS_KEY` and `PIXABAY_KEY`. The agent never prints them.
- [ ] **Step 4: Implement**, then run the tests. Expected: PASS. Commit: `git commit -am "Script writer and stock footage search"`

### Task 15: Voice, montage and render (billikalesh drafts)

**Files:**
- Modify: `pages/script_pipeline.py` (`beat_spans`, `montage`, `make_reel`, `step`), `pages/cli.py` (`work` runs both pipelines), `pages.toml` (billikalesh `music`)
- Create: `music/LICENSES.md`
- Test: `tests/test_script_pipeline.py`

**Interfaces:**
- Consumes: `writing.write_script`, `search_footage`, `voice.speak`, `clipper.render_one`, `clipper.group_segments`, `writing.write_caption`.
- Produces:
  - `beat_spans(words: list[dict], beats: list[Beat]) -> list[tuple[float, float]]`: each beat's spoken span, matching words to beats in order. Spans touch, so there are no gaps.
  - `montage(shots: list[Path], spans, voice_mp3: Path, out: Path) -> Path`: each shot `scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920`, trimmed to its span and concatenated, with the voiceover as the only audio and 1.0 s of tail.
  - `make_reel(db, cfg, page) -> int`:
    1. Script, then a shot per beat. Any beat without a shot fails the reel with "no footage for <query>".
    2. Speak the script. A length outside 18 to 50 s fails it with "script length".
    3. Montage, then write the engine workdir `work/script-<clip id>/` with `meta.json` (`path` = the montage, `language` "en"), `transcript.json` (`group_segments(words)`) and `moments.json` (one moment over the whole montage, scores 3).
    4. `render_one(theme=page.theme, music=random choice of page.music)`, then `store.put`.
    5. Caption with the credits `Footage: <author> / <provider>` per shot. Store `script` JSON with the claims and flags, and the `credits` JSON. The clip becomes `draft`, `kind="script"`.
  - `step(db, cfg)`: one `make_reel` per script page while `queue_size < QUEUE_LOW`.

- [ ] **Step 1: Write the failing tests**

```python
def test_beat_spans_cover_the_voiceover_in_order():
    words = [w("Ever", 0, .3), w("wondered?", .3, .9), w("Cats", 1.0, 1.3), w("purr.", 1.3, 2.0)]
    assert script_pipeline.beat_spans(words, [Beat(line="Ever wondered?", shot_query="a"), Beat(line="Cats purr.", shot_query="b")]) == [(0.0, 1.0), (1.0, 2.0)]

def test_make_reel_stores_claims_credits_and_a_draft(d, cfg, local_store, monkeypatch): ...
    # patched script/footage/speak (30 s)/montage/render/caption → 'draft', kind 'script', credits has 6 shots,
    # script JSON has claims; caption contains "Footage:"
def test_script_too_long_fails_the_reel(d, cfg, local_store, monkeypatch): ...  # speak → 55 s → 'failed', "script length"

@pytest.mark.slow
def test_montage_is_vertical_and_as_long_as_the_voice(tmp_path): ...  # two ffmpeg testsrc shots + 3 s tone → 1080x1920, ≈4.0 s
```

- [ ] **Step 2: Run.** Expected: FAIL.
- [ ] **Step 3 [YOU]:** download about 10 calm instrumental tracks from Pixabay Music. Record each one's title, author, URL and licence (Pixabay Content License) in `music/LICENSES.md`. The agent uploads them to `music/` in the store and lists their keys in billikalesh's `music`.
- [ ] **Step 4: Implement**, then run the tests. Expected: PASS. Then for real: `uv run pages work`. Expected: a billikalesh draft on the review page with claims, credits and a music bed. Check every claim before approving.
- [ ] **Step 5: Commit** `git commit -am "Script first pipeline: voice, montage, render"`

### Task 16: Creative Commons YouTube footage (fallback when stock runs out)

**Files:**
- Modify: `pages/fetcher.py` (`cc_search`), `pages/script_pipeline.py`
- Test: `tests/test_fetcher.py`, `tests/test_script_pipeline.py`

**Interfaces:**
- Consumes: the store protocol from Task 11.
- Produces:
  - Job `cc_search: [{"key", "query", "seconds"}]`.
  - The fetcher searches `https://www.youtube.com/results?search_query=<q>&sp=EgIwAQ%253D%253D` (the Creative Commons filter) with yt-dlp, keeps the first result whose `license` contains "Creative Commons" and that is at least `seconds + 4` long, downloads `seconds` from its middle, and uploads `footage/cc/<key>.mp4` and `footage/cc/<key>.json` (`page_url`, `author`, `licence`).
  - `make_reel` changes: a beat with no stock shot writes a `cc_search` job and leaves the reel as `waiting_footage` with its script saved. The next `step` finishes it once every key exists.
  - Credit: `Footage: <author> (CC BY) <page_url>`.

- [ ] **Step 1: Write the failing tests:** `test_cc_search_refuses_a_video_without_a_cc_licence` (a fake yt-dlp info with "Standard YouTube License" leads to no upload) and `test_reel_waits_for_cc_footage_then_finishes`.
- [ ] **Step 2: Run.** Expected: FAIL. **Step 3: Implement.** **Step 4: Run.** Expected: PASS.
- [ ] **Step 5: Commit** `git commit -am "CC BY YouTube footage via the Mac fetcher"`

---

## Phase 5: Deploy and run the pilot

### Task 17: AWS deploy behind Cloudflare Tunnel + Access

**Files:**
- Create: `deploy/bootstrap.sh`, `deploy/setup-instance.sh`, `deploy/deploy.sh`, `deploy/musubi-pages-web.service`, `deploy/musubi-pages-tick.service` + `.timer` (every 5 min), `deploy/musubi-pages-work.service` + `.timer` (every 10 min), `deploy/musubi-pages.env.example`, `README.md` (runbook)

**Interfaces:**
- Consumes: everything above. The env file sets:
  - `PAGES_HOME=/var/lib/musubi-pages`, `PAGES_STORE=s3://musubi-pages-<id>`, `PAGES_LLM=bedrock`
  - `MUSUBI_CLIPS_OFFLINE=1`, `MUSUBI_CLIPS_JOBS=1`
  - `CF_ACCESS_AUD`, `CF_ACCESS_TEAM`, `PEXELS_KEY`, `PIXABAY_KEY`

- [ ] **Step 1: Gate.** The Task 2 credits check confirmed that Bedrock is covered. If it isn't, stop and ask Prateek. The subscription CLI is for local testing only, not the server.
- [ ] **Step 2: Write `bootstrap.sh`** (profile `musubi-pages`):
  - An IAM role `musubi-pages-ec2` allowing the bucket, `bedrock:InvokeModel*`, `polly:SynthesizeSpeech` and `polly:DescribeVoices`, plus `AmazonSSMManagedInstanceCore`, with an instance profile.
  - A security group with **no inbound rules**.
  - A `t3.medium` on Ubuntu 24.04 amd64 with a 40 GB encrypted gp3 disk.
  - `setup-instance.sh` (run through SSM) installs `ffmpeg`, Node 22 (NodeSource), `uv` and `cloudflared`, creates the user `pages`, and installs the units.
  - `deploy.sh` runs `rsync` over SSH through an SSM proxy (`ProxyCommand aws ssm start-session --document-name AWS-StartSSHSession`), then `uv sync --frozen` and restarts the services.
  - Run them. Expected: `systemctl status musubi-pages-web` is active.
- [ ] **Step 3 [YOU]: Cloudflare.**
  - In Zero Trust, create a tunnel and paste its token on the instance (the agent runs `cloudflared service install <token>` through SSM). Route `ops.musubi.si` to `http://127.0.0.1:8000`.
  - Create an Access application for `ops.musubi.si` with Google as the identity provider and a policy "emails ending in @musubiclip.com".
  - Give the agent the Application Audience tag and the team domain for the env file.
- [ ] **Step 4: Move the pilot state.** Stop local `tick` and `work`. Copy `~/MusubiPages/pages.db` to the server, and move the local store to S3 with `aws s3 sync ~/MusubiPages/store s3://musubi-pages-<id>`. Point the Mac fetcher plist at `PAGES_STORE=s3://...` and load it with `launchctl load`.
- [ ] **Step 5: Smoke test on the server.**
  - `sudo -u pages pages check-aws`: Bedrock answers from the instance role.
  - A first-run render of one clip, timed. If it takes over 15 minutes, move to `t3.large` and record why.
  - https://ops.musubi.si works for prateek@musubiclip.com and returns 403 without sign in.
  - `pages tick` runs from the timer, according to `journalctl -u musubi-pages-tick`.
- [ ] **Step 6: Write `README.md`** as a runbook: daily review, the weekly Account Status check, what a pause means and how to unpause, reconnecting a token, adding a source with its permission record, deploying, and restoring a backup.
- [ ] **Step 7: Commit** `git commit -am "Deploy: EC2, systemd timers, Cloudflare Tunnel and Access"`

### Task 18: Go live and the 2 week check ([YOU] with the agent)

- [ ] **[YOU]** Approve the first drafts. Week 1 goes out as Trial Reels if Task 3 confirmed `trial_params`.
- [ ] **[YOU]** Every day for 14 days: review the drafts (10 to 15 minutes). Every week: check each page's Account Status in the Instagram app and record it on the review page.
- [ ] Day 14: export `page_metrics` for both pages to `research/pilot-day14.md`: reels posted, median views, the share of views from non followers, pauses and failures.
  - **Gate (design §5):** if podcastbawaal's non follower share is near zero, the AI layer isn't counting as original. Stop and rethink it before adding pages.
- [ ] Commit `git commit -am "Pilot: day 14 results"`
