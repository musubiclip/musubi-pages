# Postoria: research for the 10 niche Instagram pages tool

Researched 2026-10-22. Web only. "Vendor says" marks claims only the vendor makes.

## 0. Which Postoria

There is only one product called Postoria: **postoria.io**, a social media scheduler. I found no other app with the name: no postoria.com product, nothing in the Play Store, nothing on G2 or Product Hunt. The Instagram handle linked from the site is @postoria.app. It is the right one for this question.

## 1. What it is, who makes it, age, traction

- A web SaaS to plan, schedule, publish and analyse posts across 12 networks: Facebook, Instagram, LinkedIn, Google Business Profile, Threads, X, Pinterest, YouTube, TikTok, Telegram, Bluesky and Tumblr. Its API enum also lists Reddit. https://postoria.io (fetched 2026-10-22)
- **Company:** Postoria LLP, England, Companies House **OC456987**, **incorporated 4 June 2025**. The registered address is Stoney Works, 8 Stoney Lane, London SE19 3BD. Its two designated members, Nikolai Ivanov and Marina Ivanova, are both appointed 4 June 2025 and both list **Russia as their place of residence**. The site also links a vk.com page. https://find-and-update.company-information.service.gov.uk/company/OC456987/officers (fetched 2026-10-22)
- **Age:** the launch post was last updated 13 Aug 2025, so the product is about 14 months old. https://postoria.io/blog/postoria-officially-launches-all-in-one-social-media-management-platform
- **Traction (vendor says):** 3,204 active users and 1,048,071 posts in September 2026, and "10k have tried". https://postoria.io
- **Independent reviews are almost nonexistent:**
  - Trustpilot has 1 review: 5 stars, 28 Jul 2026, with a TrustScore of about 3.5 to 3.7. https://www.trustpilot.com/review/postoria.io
  - Capterra and GetApp list it with 0 reviews. https://www.getapp.com/all-software/a/postoria/
  - Toolradar lists "new tool" as a con. https://toolradar.com/tools/postoria
  - I found no G2 listing, no Product Hunt page and no Reddit threads.
- **Security incident:** on 28 Jan 2026, misconfigured file storage let anyone fetch user uploads directly. That included unpublished and scheduled post media and private YouTube and TikTok uploads. The fix was finished on 9 Feb 2026. Tokens and credentials were not involved. https://postoria.io/blog/security-incident-file-storage-misconfiguration

## 2. Features

| Feature | Status | Source |
|---|---|---|
| Reels scheduling and auto publishing | Yes. `content_type: reel`, plus a trial reel option, `auto_share_if_performs_well`, collaborators, user tags, a first comment with delay, and the `is_ai_generated` flag | OpenAPI spec (below), CSV help |
| Multiple accounts | Free: 10 accounts. Pro: 50. Agency: 500 | https://postoria.io/pricing |
| Bulk upload | CSV of up to 100 rows (10 MB), media by URL, creates drafts first, `Reel` type supported. Pro and up | https://postoria.io/help-center/bulk-upload-posts-with-csv |
| Randomized schedule | **Partial.** Queues use fixed weekly time slots. "Random" only picks *which* post fills a slot, and the slot times never vary | https://postoria.io/blog/postoria-queues (updated 2026-05-15) |
| AI captions | Yes, Pro and up | pricing |
| Analytics | Post and account metrics: views, reach, reactions, comments, shares, video metrics "depending on network", and CSV export. Post analytics cover **only posts published through Postoria**. Instagram reel views are not explicitly confirmed in its docs | https://postoria.io/help-center/how-to-use-analytics-in-postoria |
| Clip cutting from long videos | No | — |
| Auto follow, like, DM or comment engagement | **None found.** Its terms forbid bots and say connections use official authorization flows | https://postoria.io/terms-of-service (updated 2026-05-03) |

**No ToS violating feature was found:** no engagement bots, no password login, no browser automation.

## 3. How it connects to Instagram

It uses the official Meta OAuth. It offers three methods:

- Instagram Login, which needs reconnecting about once a year
- Facebook Login, which needs reconnecting about every 60 days
- Meta business portfolio, in beta

The account must be Professional, meaning Business or Creator. Postoria never receives the password. https://postoria.io/help-center/how-to-connect-an-account-to-postoria and https://postoria.io/blog/connect-instagram-postoria-via-instagram-login-facebook-login (updated 2026-09-17)

I found nothing saying it is a Meta Business Partner. That it publishes for arbitrary public users implies it passed App Review for publishing, but that is inferred, not verified.

## 4. Pricing for 10 Instagram accounts

| Plan | Accounts | Posts a month | API | Price |
|---|---|---|---|---|
| Free | 10 | **50** | none | $0 |
| Pro | 50 | 5,000 | yes | **$10/mo or $100/yr** |

Each successful publish to one account counts as one post. https://postoria.io/help-center/how-plan-limits-work

- **Free does not fit.** 10 pages at 1 to 3 reels a day is about 300 to 900 posts a month, against a cap of 50. It also has no API, no queues and no bulk upload.
- **Pro fits at $10 a month**, about ₹850 to ₹900 at roughly ₹85 to ₹88 per dollar. That exchange rate is not verified.
- Billing goes through PayPro Global or PayPal. I found no AWS Marketplace listing, so AWS credits **cannot** pay for it.

## 5. API or webhook

There is a Public API v1 on Pro and Agency. https://postoria.io/blog/postoria-public-api (updated 2026-08-18). Reference: https://api.postoria.io/v1/docs. Spec: https://api.postoria.io/v1/openapi.json (downloaded 2026-10-22).

- **Authentication:** a Bearer key. Rate limit: 300 requests per 5 minutes.
- **Media:** upload through a presigned PUT then a complete call, or import from a public HTTPS URL (an S3 presigned URL works). Then poll until the media is `ready`.
- **Posts:** `POST /v1/workspaces/{id}/posts` with `publish_mode` set to `publish_now`, `schedule` (an exact UTC `scheduled_time`) or `queue`.
- **Analytics:** `GET .../analytics/posts?post_ids=` returns metrics for 1 to 100 posts as name and value pairs. A summary endpoint groups metrics by social account.
- **No webhooks.** You poll.
- Accounts can be connected through the API too.

So an internal tool *could* hand off fully reviewed clips. It would pick its own random time per page and call `schedule`, then poll analytics. That would replace the publishing and insights calls entirely.

## 6. Verdict: skip, at most a one month trial

1. **It adds nothing you do not already plan to have.**
   - The internal tool already calls the same official Instagram API with Instagram Login. For your own 10 pages, Standard Access with the accounts as testers works without App Review.
   - Postoria would replace about three Graph API calls: create a container, publish, and read insights.
   - It does **not** give random timing. You would still compute the times yourself.
2. **Ban risk is the same either way.** Instagram judges content and behaviour, not which official API client posted. For reposted YouTube clips the real risk is Instagram's unoriginal content rules, and no scheduler changes that.
3. **It costs money outside AWS**, $10 a month, which breaks the "nothing paid outside AWS credits" rule.
4. **Vendor risk is high for a component that would hold publish tokens for all 10 pages:**
   - the company is 16 months old, with almost no independent reviews
   - it had a storage exposure of unpublished media in January 2026
   - its members reside in Russia, a continuity, payments and compliance consideration
   - if its Meta app is restricted, every page stops posting at once.
5. **Analytics are weaker than direct insights.** Its post metrics cover only Postoria-published posts, reel views on Instagram are not explicitly documented, and the Instagram insights endpoint already returns `views` per reel.

**If anything:** use Pro for one month as a stopgap, publishing through its API with your own random `scheduled_time`, only if the direct Graph API publisher would be late. Keep the publisher interface thin so it can swap back.
