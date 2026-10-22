# Instagram API check (verify-ig), 23 Oct 2026

Run against @tech_bawaal (Instagram user id 17841424018966348) through the "Musubi Pages" Meta app (1488230259790933), Instagram Login, Standard Access, API v26.0. One test container was created from a 5 second test video and never published.

| Unknown | Result | What the tool does |
|---|---|---|
| content_publishing_limit | 100 posts per 24 hours (usage 0) | Reads it before every publish |
| trial_params (Trial Reels) | Rejected: "Application does not have permission for this action" | `trial_reels = false`; first posts go out as normal reels |
| is_ai_generated (AI info label) | Accepted | Sent on every reel |
| copyright_check_status | Not available: "Tried accessing nonexisting field" | `copyright_check = false`; rely on licence records, no music moments, licensed beds only (design §6.4) |
| views by follower_type | Not returned (page has no views yet) | `follower_type_views = false`; recheck after the first posts |
