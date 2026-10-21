# Musubi Pages: design

Date: 2026-10-22. Status: draft for Prateek's review.

## 1. What this is and why

Musubi will own a network of niche Instagram pages (27 planned, Hinglish handles such as `podcastbawaal`, `sipkarobhai`, `billikalesh`). Today the pages grow reach. Later they become distribution Musubi can sell to brands, on top of its creator clipping marketplace.

Musubi Pages is a separate internal tool that keeps those pages posting good reels every day with little human time. It turns long videos into short vertical clips, adds an original layer of commentary to each, lets one person approve a daily batch, publishes through the official Instagram API at varied times, and tracks views per reel.

**The pilot is one page: `billikalesh`** (animals and nature). It already exists as a Creator account with name, bio and photo. Everything below is built and proven on it first; the other 26 pages are added as they are created over the coming days, mostly as configuration.

## 2. Goals, non goals, anti goals

**Goals**
- billikalesh posts 1 reel a day within the first week of the tool running, rising to 2 or 3 when reach holds.
- A person spends about 10 to 15 minutes a day reviewing, for all pages together.
- Each page's median reel passes 5,000 views by day 90 of posting. A page under 1,000 after 60 days gets a new angle or is replaced.
- Adding a new page takes minutes: connect the account, set its sources, voice and style.

**Non goals (v1)**
- Anything for brands: no brand posts, pricing or paid partnership labels.
- YouTube Shorts or any platform other than Instagram.
- Facebook cross posting.
- Engagement automation of any kind.

**Anti goals: if the tool does any of these, it has failed even if it works**
- Automated following, unfollowing, liking, commenting or DMs. No API offers them; only bots do, and they get accounts blocked.
- Posting a clip with no original layer. Instagram stops recommending accounts whose posts are mostly other people's content (rule announced 2026-04-30).
- Posting the same clip to two pages, or one we know the source already posted on Instagram.
- Posting without the copyright check, or with music left in.
- Proxies, antidetect browsers or anything that hides who runs the pages. One company openly owning many pages is allowed; disguising it is what Meta punishes.
- Touching Musubi's marketplace systems: the musubi-platform app, its Meta app, or the WhatsApp number that sends creator login codes.

## 3. Constraints and facts the design rests on

Researched 2026-10-22. Full notes with sources are in `research/` (`research-growth.md`, `research-spam.md`, `research-api.md`, `research-postoria.md`).

**Instagram API (Instagram Login, API v26)**
- Publishing to accounts Musubi owns needs only **Standard Access**: each page is added to the app as an Instagram tester. No App Review and no business verification. Limit: 50 testers per app.
- Permissions: `instagram_business_basic`, `instagram_business_content_publish`, `instagram_business_manage_insights`.
- Tokens are long lived (60 days) and can be refreshed after 24 hours. A token not refreshed within 60 days dies, and the page must be reconnected by hand.
- Reels: MP4 or MOV, H.264 or HEVC, AAC, 3 seconds to 15 minutes, up to 300 MB. `video_url` must be a **public URL** at publish time, because Instagram Login has no resumable upload.
- Supported: `share_to_feed`, cover (`cover_url` or `thumb_offset`), **Trial Reels** (`trial_params`), up to 3 `collaborators`.
- Posts per page per day: the docs say 50 in one place and 100 in another, so read `content_publishing_limit` at runtime.
- Not available: Instagram library music (it can only rename original audio), the paid partnership label, Account Status, and follows per reel.
- Reel insights: views, reach, likes, comments, saves, shares, total interactions, average watch time, total watch time. Account level `follows_and_unfollows` needs 100+ followers. Account insights are kept for 90 days only, so we store our own copy.
- Rate limit: 4,800 × impressions per 24 hours per account. New pages with low reach get little headroom, so poll insights sparingly.
- Errors 2207050 (account restricted) and 2207051 (suspected spam) come back on publish. They are the only automatic signal of trouble.
- The Meta app needs a public privacy policy URL and a data deletion path, even when only testers use it.
- `copyright_check_status` is documented under the Facebook Login version only. **Test it with an Instagram Login token in the pilot.** If it doesn't work, the copyright check falls back to the steps in §6.4.

**What grows a page now**
- Instagram's top signals are watch time, sends per reach, and likes per reach. It also favours originality and recent posts, and tests reels from small accounts on non followers.
- An account gets non follower reach only if **most of its posts in a rolling 30 days are original**. Subtitles, borders, a caption credit and the owner's permission do not count. Commentary, context that adds information, voiceover, or a reaction do. Instagram's test: if your contribution could be removed and the clip would be virtually the same, it isn't original.
- Only the first copy of a moment gets recommended. If the source posted that moment on Instagram first, our copy loses.
- Reels up to 3 minutes are recommended; longer ones reach followers only. Views peak at 45 to 60 seconds.
- At most 5 hashtags, and they barely matter. Keywords in captions do, because Google indexes professional accounts' posts.
- Scheduling and API posting don't affect reach (Mosseri, 2025 and 2026).
- Topics Instagram doesn't recommend: exaggerated health claims, cosmetic procedures, get rich schemes, miracle or astrology claims. These matter for the finance, fitness, beauty and spirituality pages.

**Bans**
- Meta can disable accounts owned by the same person or entity as a disabled one. The 27 pages share a laptop, a network, an email domain and a Meta app, so **one bad page can take all of them down**. Strict hygiene on every page protects the others.
- Creating accounts in bursts and engaging at high frequency are named in Meta's spam policy. One page already hit a phone checkpoint and is in appeal (22 Oct). The rest are being created over several days.

## 4. Decisions already made

| Area | Decision |
|---|---|
| Platform | Instagram only, for now |
| Pages | 27 angles; pilot `billikalesh` |
| Tool home | New standalone app, separate from musubi-platform and Musubi Log |
| Runtime | AWS, Mumbai (`ap-south-1`), paid from Musubi's $1000 credits. Cutting runs on AWS too |
| Instagram access | One **new** Meta app just for the pages, separate from the marketplace app; Instagram Login; each page a tester |
| Sources | Only sources that allow clipping. Permission recorded per source |
| Intake | Both: watched source channels, and pasted links |
| Original layer | AI writes it (voiceover intro and takeaway, on screen context cards). A human checks it. Voice via Amazon Polly |
| Review | One person approves a daily batch: video, hook, caption. Approve, edit caption, or reject |
| Captions | AI writes a fresh caption per clip: source credit plus at most 5 hashtags. Reviewer can edit |
| Clip look | musubi-clips engine (animated hook, word highlighted captions, no pitch cards, no Musubi watermark), each page with its own font, colours and hook style |
| Cadence | Week 1: Trial Reels. Then 1 a day, rising to 3 if reach holds. Random times between 9am and 11pm IST, at least 3 hours apart, an occasional skipped day, different pattern per page |
| One clip | goes to one page only |
| Collaborators | Source's Instagram added as collaborator when the source agreed to it during the licence conversation |
| Success | Median views per reel; 5,000 by day 90; under 1,000 after 60 days means change the angle or replace the page |
| Ownership | Pages owned openly; nothing disguises that Musubi runs them |
| Accounts | Signed up by hand on `<username>@musubi.si` (forwards to the pages@musubiclip.com Google Group); 2FA by authenticator; credentials in Bitwarden; never linked in one Accounts Center |
| Not used | Postoria, or any third party scheduler |

## 5. Pilot scope

v1 is one page end to end:

1. **Connect** billikalesh to the new Meta app as a tester and store its token.
2. **Sources** for animals and nature (open question in §9).
3. **Cut** clips, **add the original layer**, **render** them in billikalesh's style.
4. **Review** in a simple web page.
5. **Publish** as Trial Reels first, then normal reels, at varied times.
6. **Measure** views per reel and the share of reach from non followers. That share is the test of whether the AI original layer counts as original.

The pilot is done when billikalesh has posted daily for 2 weeks through the tool with no manual steps except review. At that point, check whether non follower reach is near zero; if it is, the original layer needs a rethink before scaling.

## 6. How it works

### 6.1 Pieces

One small server, one bucket, AWS managed AI. No queues or microservices until volume needs them.

- **App server**: one EC2 instance (start with `t4g.small`; move to a larger instance or a separate worker only when render time demands it). It runs:
  - a small web app for the review page and settings, behind Google sign in limited to musubiclip.com accounts;
  - a scheduler loop for intake, cutting, publishing, insights and token refresh;
  - a SQLite database on the instance disk, backed up to S3 every night.
- **S3 bucket** for source media, rendered clips and backups. Rendered clips are served to Instagram through short lived presigned URLs (a public URL is required at publish time). Media is deleted 30 days after posting.
- **Amazon Bedrock (Claude)** to pick moments, write the original layer and write captions. Check that the AWS credits cover Bedrock; some grants exclude it.
- **Amazon Polly** for voiceover, one voice per page.
- **Rendering**: the musubi-clips engine (Python `clipper.py` with ffmpeg, yt-dlp, and HyperFrames on Node 22) installed on the server. A GPU is not needed for rendering. Transcription uses YouTube's captions when present (the engine already does this); otherwise Whisper on CPU, slow but fine at pilot volume.

**Language:** Python for the app (my call, changed from the earlier TypeScript). The cutting engine, Whisper and yt-dlp are all Python, and Kizuna is already FastAPI. Rendering stays a Node subprocess.

### 6.2 Data

Plain tables; the names are a suggestion.

- `pages`: handle, angle, Instagram user id, token and expiry, style (font, colours, hook style), Polly voice, posting window, current daily target, paused flag and reason.
- `sources`: page, kind (YouTube channel, single link, stock library, Creative Commons), URL, permission record (who agreed, when, how, a link to the proof, whether collaborator invites are OK, the source's Instagram handle), active flag.
- `source_videos`: source, video id, title, published date, status (new, prepared, cut, skipped, failed).
- `clips`: source video, page, start and end, transcript text, original layer text, voiceover file, rendered file, caption, hashtags, collaborator, status (draft, approved, rejected, scheduled, published, failed), scheduled time, Instagram media id, trial flag.
- `insights`: clip, fetched at, views, reach, likes, comments, saves, shares, average watch time, follower share if available.
- `events`: page, time, kind, detail. This is the log of publish errors, pauses and token refreshes.

### 6.3 Daily flow

1. **Intake** (hourly): look for new uploads on each page's watched sources and add pasted links. A pasted link must belong to an allowed source, unless the reviewer marks it as a one off with a permission note.
2. **Prepare and pick**: fetch the transcript, and Claude picks candidate moments with the musubi-clips rules: stands alone, stays on topic, 30 to 90 seconds, nobody cut mid sentence. Skip moments that are music beds or contain recognisable songs. Skip moments the source already posted on its own Instagram, when that can be checked.
3. **Original layer**: Claude writes a 3 to 6 second voiceover intro in the page's voice, a closing takeaway of about 3 seconds, and 1 to 3 on screen context cards with facts the clip itself doesn't say. Polly voices the intro and takeaway.
4. **Render**: crop to full 9:16 (never letterboxed in a frame), then add the page's hook, captions and cards, and remove any music. Strip or avoid YouTube player UI and other watermarks.
5. **Caption**: Claude writes a caption with searchable keywords, a credit line ("Video: @source" or the channel name), and at most 5 hashtags. Never the same text twice.
6. **Review** (once a day): the review page lists each page's new clips with player, hook, layer text, caption and source permission. Approve, edit the caption, or reject with a reason. Restricted topic flags show here.
7. **Schedule**: each approved clip gets a random slot in its page's window (9am to 11pm IST, at least 3 hours from the page's last post, the page's daily target not exceeded, an occasional day skipped).
8. **Publish**: create the container with a presigned URL; poll until it finishes; run the copyright check if it works with our tokens; publish. Week 1 and any test hook go out as Trial Reels.
9. **On error**: 2207050 or 2207051 **pauses that page** and records the event. A paused page publishes nothing until a person unpauses it. Other errors retry twice, then mark the clip failed.
10. **Insights**: fetch each reel at 1 hour, 24 hours, 72 hours and 7 days. Weekly, compute each page's median views and the share of views from non followers.
11. **Token refresh**: refresh every page's token weekly. Warn on the review page 10 days before any token expires.

### 6.4 Copyright hygiene

- Every source has a permission record before any of its clips can be approved. Written permission (email or signed note) names all of Musubi's handles, not just one page, so moving a source between pages stays covered.
- Sources that use Meta Rights Manager or YouTube Content ID are asked to allowlist our handles.
- Music: drop clips whose audio carries a recognisable song, and remove background music where the engine can separate it.
- Studio, broadcast and league footage (films, OTT, cricket, football): the source creator's permission doesn't cover footage they don't own. For those pages, the original layer must carry the post: talking head commentary, graphics or stock footage, with only brief excerpts. This is the riskiest part of the network; Prateek chose to run these pages anyway.

### 6.5 Account health

- Someone checks each page's **Account Status** in the Instagram app weekly ("can your content be recommended?"). The API doesn't expose it. Record the result in the tool.
- A page that becomes not recommendable is paused and its last 30 days reviewed before it posts again.

## 7. Cost (pilot, monthly, rough)

| Item | Estimate |
|---|---|
| EC2 `t4g.small`, disk, public IP | ~$18 |
| S3 storage and requests | ~$1 |
| Bedrock (Claude), pilot volume | a few dollars |
| Polly | under $1 |
| Data out | $0 (under 100 GB free) |
| **Total** | **~$20 to $25**, from AWS credits |

At 27 pages the server will need more CPU for rendering. Plan on ~$40 to $80 a month then, plus whatever is spent on getting downloads through YouTube (§8).

## 8. Known risks

- **YouTube blocks downloads from AWS** ("Sign in to confirm you're not a bot"). Prateek will solve it as it comes. Built in from the start: an "upload the file" option on the review page, so a blocked download never stalls a page. Options later: sources send files directly, or a residential proxy that fetches only the chosen segments.
- **Whether AI narration counts as original is untested.** The pilot measures it (§5).
- **One flagged page endangers all 27.** Mitigated by per page pause, copyright hygiene, and slow account creation.
- **Token expiry.** A page silently stops posting if its token lapses. Mitigated by weekly refresh and warnings.
- **Copyright check may not work with Instagram Login tokens.** Test in the pilot.

## 9. Open: decide before building

1. **Where billikalesh's clips come from.** Animal and nature content is mostly short viral clips owned by many individuals, not long videos from a few sources. Candidates: animal creators who agree to clipping; YouTube videos under the Creative Commons Attribution licence (reuse is allowed with credit); free stock footage (Pexels, Pixabay) as the base for fact driven reels with voiceover. The pick changes intake for this page.

## 10. Left to the builder

- Instance size, process layout, the review page's look, the SQLite schema details, retry timing.
- Per page style presets beyond billikalesh.
- The Meta app's privacy policy and data deletion pages (static pages are fine).
- Repository: a new private repo in the musubiclip GitHub org. It is not musubi-platform, so that repo's rules (`CLAUDE.md`, the @staging flow) don't apply unless Prateek wants them.
