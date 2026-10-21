# Instagram API with Instagram Login for an internal reels tool: checked against Meta docs (2026-10-22)

Source: the docs' Markdown copies (`developers.facebook.com/documentation/instagram-platform/*.md`, listed in `/documentation/instagram-platform/llms.txt`). The URLs below are the `/docs/` pages. The API is at v26.0. The newest changelog entry is dated 2026-07-30.

## 1. Publish reels to a Creator account with no Facebook Page: TRUE
- "Instagram API with Instagram Login serves Instagram professional accounts without requiring a linked Facebook Page." In the comparison table, Facebook Page is "Not required" and Content publishing is "Supported". https://developers.facebook.com/docs/instagram-platform/overview#which-api-is-right-for-my-app
- "An Instagram professional account can represent a business or creator." (same page). `/me` `account_type` "Can be `Business` or `Media_Creator`." https://developers.facebook.com/docs/instagram-platform/instagram-api-with-instagram-login/get-started
- The Content Publishing requirements table lists Instagram Login with Access Levels "Advanced Access, Standard Access", host `graph.instagram.com`, and permissions `instagram_business_basic` and `instagram_business_content_publish`. https://developers.facebook.com/docs/instagram-platform/content-publishing

## 2. Standard Access, testers, invites: TRUE, with caveats
- "Standard Access is the default access level ... intended for apps that will only be used by people who have roles on them ... If your app only serves your Instagram professional account or an account you manage, Standard Access is all your app needs." https://developers.facebook.com/docs/instagram-platform/overview (Access levels)
- App Review table: "My app is only for a business I own or manage. | No login or Instagram Login | Standard Access | Not required". https://developers.facebook.com/docs/instagram-platform/app-review
- "Standard Access if your app serves Instagram professional accounts you own or manage and have added to your app in the App Dashboard." https://developers.facebook.com/docs/instagram-platform/instagram-api-with-instagram-login/business-login
- Business apps "are automatically approved for Standard Access for all permissions and features available to their app type." https://developers.facebook.com/docs/graph-api/overview/access-levels
- "Business apps do not have app modes and instead rely exclusively on access levels". So the rule that "posts made in Development mode are seen only by role users" does not apply. https://developers.facebook.com/docs/development/create-an-app/app-dashboard/app-types
- **How an account is added (current docs):** Step 7 says "Add an Instagram account. This account must be public. Multiple accounts can be added for multiple testers. You will be prompted to login to your Instagram account. You can add or remove accounts at any time by clicking App Roles > Roles or Instagram > API Setup with Instagram login". https://developers.facebook.com/docs/instagram-platform/create-an-instagram-app
- **Where the invite is accepted:** the current Instagram Login docs never describe this. The only official wording is in the retired Basic Display guide (archived 2024): "Navigate to (Profile Icon) > Edit Profile > Apps and Websites > Tester Invites and accept the invitation." On the web that is instagram.com/accounts/manage_access, the "Tester invites" tab. Third party guides from 2025 and 2026 say the same. When an account is added through the Step 7 Instagram login popup, it does not appear to need a separate accept, but this is not verified. https://web.archive.org/web/2024/https://developers.facebook.com/docs/instagram-basic-display-api/getting-started
- **Limits:** "Most apps, not linked, can have up to 50 testers." An app linked to a verified business portfolio can have "up to a combined total of 500 analytics users and testers." So 10 accounts is fine. https://developers.facebook.com/docs/development/build-and-test/app-roles
- **Policy on testers:** "You may only add a person as a Tester to your app if they are your employee or you have an agreement with them which establishes that they are acting on your behalf". Accounts the company owns and runs meet this (same page).
- **Caveats:**
  - "Because of the limited scope of Standard Access, some features might not work properly until your app has been granted Advanced Access." (overview)
  - Create-app Step 10 says "Instagram requires successful completion of the App Review process before your app can access live data". This contradicts the overview and App Review pages, which are the more specific ones.
  - "Your app can either use Facebook Login or Instagram Login but not both" (app-review page), so a separate app is the right call.
  - Developers and admins are capped at "a maximum of 15 apps" not tied to a verified business (create-an-instagram-app).

## 3. Permissions and tokens: TRUE
- Publishing needs `instagram_business_basic` and `instagram_business_content_publish`. https://developers.facebook.com/docs/instagram-platform/content-publishing
- Insights (media and account) need `instagram_business_basic` and `instagram_business_manage_insights`. https://developers.facebook.com/docs/instagram-platform/reference/instagram-media/insights
- The app-review page spells the permission `instagram_business_content_publishing`. The scope string is `instagram_business_content_publish` (business-login page).
- Tokens: the authorization code is valid 1 h and the short-lived token 1 h. The long-lived token "is valid for 60 days and can be refreshed before they expire" (overview). "Access tokens from the App Dashboard are long-lived and are valid for 60 days" (get-started). This means a tool with no login flow can generate one token per account in the dashboard.
- Refresh rules: "Refresh a long-lived accesstoken that is at least 24 hours old but has not expired. Refreshed tokens are valid for 60 days from the date at which they are refreshed." Call `GET graph.instagram.com/refresh_access_token?grant_type=ig_refresh_token`. https://developers.facebook.com/docs/instagram-platform/reference/refresh_access_token
- "Tokens that have not been refreshed in 60 days will expire and can no longer be refreshed." The exchange call uses the app secret and is server side only (business-login page).
- "If your app serves only your Instagram professional accounts ... you do not need to implement a login flow." (overview)

## 4. Publishing limits and reel parameters: PARTLY (the docs contradict each other on the daily cap)
- **Daily cap.** The guide says "Instagram accounts are limited to 100 API-published posts within a 24-hour moving period. Carousels count as a single post." https://developers.facebook.com/docs/instagram-platform/content-publishing
  - The same page's carousel section says "Accounts are limited to 50 published posts within a 24-hour period."
  - The reference says `quota_total` is "currently `50`", with `quota_duration` 86400. https://developers.facebook.com/docs/instagram-platform/instagram-api/reference/ig-user/content_publishing_limit
  - **Verdict: 50 or 100. Read `GET /<IG_ID>/content_publishing_limit?fields=config,quota_usage` at runtime.** Going over returns error 9 / 2207042. Either number is far above a sane posting rate.
- **Containers.** "An Instagram account can only create 400 containers within a rolling 24 hour period"; "Containers expire after 24 hours". Poll `status_code` (IN_PROGRESS, FINISHED, ERROR, EXPIRED, PUBLISHED) "once per minute, for no more than 5 minutes". https://developers.facebook.com/docs/instagram-platform/instagram-api/reference/ig-user/media
- **Reel type and source URL.** Use `media_type=REELS` with `video_url`: "We cURL media used in publishing attempts, so the media must be hosted on a publicly accessible server". A presigned S3 URL is fine.
  - Resumable upload (`upload_type=resumable`, `rupload.facebook.com`) is "Only for apps that have implemented Facebook Login for Business." With Instagram Login, it is a public URL only.
  - A published reel reads back `media_type=VIDEO`.
- **Reel video spec:**
  - Container: MOV or MP4 "no edit lists, moov atom at the front of the file".
  - Video: HEVC or H264, progressive, closed GOP, 4:2:0, 23 to 60 FPS, at most 1920 px wide, VBR at most 25 Mbps.
  - Audio: AAC, at most 48 kHz, mono or stereo, 128 kbps.
  - Aspect "between 0.01:1 and 10:1 but we recommend 9:16".
  - Duration "15 mins maximum, 3 seconds minimum"; file size "300MB maximum".
  - Cover: JPEG at most 8 MB, cropped to 9:16 (1:1 on the feed). (ig-user/media page)
- **`share_to_feed`:** TRUE. When true the reel can appear in Feed and Reels tabs, but "Neither value determines whether the reel actually appears in the Reels tab". The resumable example omits it.
- **`cover_url` / `thumb_offset`:** TRUE. If both are set, `cover_url` wins. `thumb_offset` is in ms, default 0.
- **`collaborators`:** PARTLY. The parameter is "up to 3 instagram usernames", for Feed image, Reels and Carousels. But the overview's Collaborators section is headed "Facebook Login for Business only." It is unclear whether that covers invite at publish or only reading co-authored data. Test on graph.instagram.com.
- **`location_id`:** PARTLY. It takes "The ID of a Page associated with a location", found via the Pages Search API, which an Instagram Login token cannot call. A known location Page ID can be hard coded. Not confirmed to work on graph.instagram.com.
- **`user_tags`:** PARTLY. It works for reels by username (x/y applies only to images and stories). But the Instagram Login page says "This API setup cannot access ads or tagging." Test it.
- **Trial reels:** TRUE. `trial_params={"graduation_strategy":"MANUAL"|"SS_PERFORMANCE"}`, with `media_type=REELS`. "Trial reels are reels that are only shared to non-followers." The 2025-12-03 changelog says trial reels are supported in both Facebook Login and Instagram Login. https://developers.facebook.com/docs/instagram-platform/changelog
- **`audio_name`:** TRUE, but limited. It only renames the original audio: "You can only rename once". "Music tagging is only available for original audio."
- **Library music:** FALSE via Instagram Login. The Instagram Audio API (`GET /ig_audio`, then `audio_configuration={audio_id,...}` at container creation) launched 2026-06-01. Its docs say: "This API is only available on the Instagram API with Facebook Login. It is not supported on the Instagram API with Instagram Login." It returns only "audio that has been authorized for third party use"; the changelog calls it "royalty-free music from Meta's Sound Collection". https://developers.facebook.com/docs/instagram-platform/content-publishing/audio-api
- **Also available:**
  - `is_ai_generated=true` applies the AI info label, on both login types (changelog 2026-06-22).
  - Caption limits: 2200 characters, 30 hashtags, 20 @ tags.
  - Not supported: shopping tags, filters, stickers. `alt_text` is not supported on reels.

## 5. Paid partnership label: FALSE for Instagram Login
- The label is set with `is_paid_partnership` and/or `branded_content_sponsor_ids` (2026-04-22). The docs say: "Available for Instagram API with Facebook Login only". It also needs `instagram_branded_content_creator` or `instagram_basic`, and branded content tools enabled on the account. https://developers.facebook.com/docs/instagram-platform/content-publishing#partnership-ads-label
- A sponsored reel published through this tool must have the label added by hand in the app afterwards. Alternatively, use a Facebook Login app, which requires a Page linked to each account.

## 6. Insights: PARTLY. `views` replaced plays and impressions, but **`follows` is not available per reel**
- Changelog 2025-01-21: `views` added. Deprecated for v22.0+, and for all versions from 2025-04-21: `plays`, `clips_replays_count`, `ig_reels_aggregated_all_plays_count`, `impressions`.
- **Reel metrics:**
  - `views`, `reach`, `likes`, `comments`, `saved`, `shares`, `reposts`, `total_interactions`
  - `ig_reels_avg_watch_time`, `ig_reels_video_view_total_time`, `reels_skip_rate`
  - `crossposted_views` and `facebook_views` (these throw if the reel is not shared to Facebook)
  - `total_views`, `total_likes` and `total_comments` are "Facebook Login only".
  - https://developers.facebook.com/docs/instagram-platform/reference/instagram-media/insights
- **`follows`**, `profile_visits` and `profile_activity` are listed for "`FEED` (posts), `STORY`" only, **not REELS**. Per reel follower attribution is not possible.
- **Media insight limits:** data "can be delayed up to 48 hours", it is "stored for up to 2 years", and an empty set is returned instead of 0. "Insights webhook for Instagram API with Instagram Login is not supported." `views`, `reach` and `total_interactions` are labelled "in development" or "estimated".
- **Account metrics:** `follows_and_unfollows` (period `day`, `total_value`, breakdown `follow_type`, "Not returned if the IG User has less than 100 followers").
  - Also: `views` (breakdown `follower_type` / `media_product_type`), `reach`, `accounts_engaged`, `total_interactions`, `likes`, `comments`, `saves`, `shares`, `reposts`, `profile_links_taps`, and demographics (100+ followers).
  - `follower_count` is named only in the limitations ("not available ... with fewer than 100 followers") and is missing from the current metric table. Use the `followers_count` field on `/me` for daily snapshots instead.
  - "User Metrics data is stored for up to 90 days."
  - https://developers.facebook.com/docs/instagram-platform/api-reference/instagram-user/insights and https://developers.facebook.com/docs/instagram-platform/insights

## 7. Account Status or recommendation eligibility via API: TRUE, there is none
- The IG User fields are: biography, followers_count, follows_count, has_profile_pic, id, is_published, media_count, name, profile_picture_url, shopping_product_tag_eligibility, username, website. None of them is account status or eligibility. https://developers.facebook.com/docs/instagram-platform/instagram-api/reference/ig-user
- The closest signals:
  - Publish errors: 25 / 2207050 "The Instagram account is restricted" ("inactive, checkpointed, or restricted"), and 4 / 2207051 "suspected to be spam". https://developers.facebook.com/docs/instagram-platform/instagram-api/reference/error-codes
  - `copyright_check_status` on the container and `copyright_check_information` on the media.
  - `boost_eligibility_info`, which covers ad boosting, not recommendations, and is Facebook Login only.
  - `is_shared_to_feed` explicitly does not mean the reel is in the Reels tab.

## 8. Rate limits and policy: no rule forbids the plan; a privacy policy and deletion path are still owed
- **Rate limit.** This is per 24 h, not per hour: "Calls within 24 hours = 4800 * Number of Impressions", counted "for each app and app user pair", where impressions are counted over the last 24 h. Throttling returns code 80002 and the `X-Business-Use-Case-Usage` header.
  - Risk: a brand new account with near zero impressions gets a tiny budget by this formula. Any floor is undocumented, so keep polling light.
  - https://developers.facebook.com/docs/instagram-platform/overview#rate-limiting and https://developers.facebook.com/docs/graph-api/overview/rate-limiting
- **Platform Terms (last updated 2026-02-03).** Nothing restricts posting to accounts the developer owns. "App" means "any technical integration with Platform", with no internal-only or tester exemption.
  - 4.a: "You will provide, maintain, and comply with a privacy policy" that is "publicly available, easily accessible", with its URL entered in the App Dashboard.
  - 4.b: "The right to request deletion must be available to all Users who can access your App."
  - 3.d.i: delete Platform Data when it is "no longer necessary for a legitimate business purpose".
  - https://developers.facebook.com/terms/
- **Dashboard fields.** The business login settings include a Redirect URL, a "Deauthorize callback URL" and a "Data deletion request URL" (create-app Step 9). Basic settings lists the Privacy Policy URL; Terms of Service URL, icon and category are "required to switch your app to Live mode", which does not apply to Business apps. Whether the dashboard blocks saving without the deletion and deauthorize URLs is not verified; reusing the musubiclip.com privacy page is the cheap path. https://developers.facebook.com/docs/development/create-an-app/app-dashboard/basic-settings
- **Developer Policies:**
  - "Don't participate in any program that promotes or facilitates the purchase, sale, or exchange of" likes and followers.
  - Spam includes "creating bots ... at very high frequencies" and "facilitating or encouraging inauthentic behavior."
  - Nothing bans coordinated posting across your own accounts.
  - https://developers.facebook.com/devpolicy/
- **Community Standards (spam).** Bars posting "manually or automatically, at very high frequencies". It names "posting repetitive content" as a signal that can add to restrictions. Reposting the same clip across the 10 accounts is the real enforcement risk, not the API. https://transparency.meta.com/policies/community-standards/spam/

## 9. Business verification for Standard Access: NOT NEEDED
- "If your app will only be used by app users who have a role on the app itself you do not need to complete verification; these users can grant your app any permissions at any time and all features are always active." https://developers.facebook.com/docs/development/release/business-verification
- "You must complete Business Verification if your app requires Advanced Access" (overview).
- A verified business raises the tester cap from 50 to 500 and lifts the 15 app cap per developer. Neither matters for 10 accounts.

## What breaks or bends the plan
1. **No follows per reel.** Follow attribution must come from the account's daily `follows_and_unfollows` (only with 100+ followers) or from `followers_count` snapshots compared against post times.
2. **No paid partnership label and no library music with Instagram Login.** Both are Facebook Login only, and an app cannot use both login types.
3. **No resumable upload.** Each reel must sit at a public URL (for example a presigned S3 link) when the container is created.
4. **The daily cap is stated as both 50 and 100.** Read `content_publishing_limit` and do not hard code either.
5. **The tester invite path is undocumented for Instagram Login.** Adding each account via the dashboard's "Add account" login popup is the documented route.
6. **A privacy policy URL and a deletion path are owed under Platform Terms** even with testers only.
