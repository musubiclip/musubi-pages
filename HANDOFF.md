# Musubi Pages: handoff

Written 2026-10-22 at the end of the planning session. Read this first, then `design.md`, then `research/` as needed.

## In one paragraph

Musubi will run 27 niche Instagram pages with Hinglish handles and grow them with clips. Later they become distribution to sell to brands. This folder is the home of the internal tool that keeps those pages posting: it cuts long videos into vertical clips, adds an AI written original layer (voiceover, context cards), lets one person approve a daily batch, publishes through the official Instagram API at varied times, and tracks views. It runs on AWS in Mumbai. **The pilot is one page, `billikalesh`.** Nothing is built yet.

## Where things stand

**Done**
- Research on growth, spam and bans, the Instagram API, and Postoria (rejected). It's in `research/`, and the conclusions are folded into `design.md` §3.
- Sign up emails. `musubi.si` is on Cloudflare (account of developer@musubiclip.com). Email Routing forwards `<username>@musubi.si` for all 27 usernames to the Google Group **pages@musubiclip.com** (owners: developer@ and prateek@; invite only; accepts outside mail). Catch-all is off. A new address is one more routing rule.
- **billikalesh** is a finished Creator account: name "Billi Kalesh", bio "Daily cat chaos, dog drama and wild nature moments 🐾 / Tag us in your pet's best fails", category Digital creator (hidden), avatar in `assets/pages/billikalesh/avatar.jpg`, 0 posts.
- The design is written (`design.md`), with a builder check pending (see "Open" below).

**In progress (Prateek, by hand)**
- Two factor login on billikalesh (authenticator app; key and backup codes saved in Bitwarden).
- The other accounts, created over the coming days at 3 to 5 a day. One new account hit a phone checkpoint and is **in appeal (submitted 22 Oct)**. Its handle wasn't recorded; ask.
- Buying 1 or 2 prepaid SIMs just for the pages. **Do not** use Musubi's WhatsApp Business number, which sends marketplace login codes.
- Setting up Bitwarden with one item per page: handle, email, password, TOTP key, backup codes, which SIM, whose birthday (one real adult, the same on all), created date.

## The 27 pages

| # | Angle | Handle | Backups |
|---|---|---|---|
| 1 | Podcast clips | podcastbawaal | podscenehai, podloredaily |
| 2 | Explainers | explainedfrbhai | lorekholdo |
| 3 | Mindset | lockedinbhai | auragrinddesi, maincharacterbhai |
| 4 | Personal finance | sipkarobhai | moneymaxxingdesi |
| 5 | Startups and founders | foundermodebhai | startupkalesh, dhandhalore |
| 6 | AI tools | aicookedus | aimaxxingdesi, promptkarobhai |
| 7 | Gadgets and apps | unboxkarobhai | gadgetauradesi |
| 8 | Sketches | sketchbawaal | lolbhaukaal, hasayegabhai |
| 9 | Memes | relatablefrbhai | none |
| 10 | Movies and OTT | filmylorebhai | ottkalesh, postcreditbhai |
| 11 | Music and dance | loopkardebhai | repeatpebhai |
| 12 | Recipes | tadkabawaal | masalamaxxing, rasoibhaukaal |
| 13 | Street food | chatpatabawaal | thelabhaukaal |
| 14 | Workouts | gymbhaukaal | pumpbawaal, repskarobhai, gymlorebhai |
| 15 | Nutrition and wellness | lowcortisoldesi | sehatbawaal |
| 16 | Beauty and fashion | fitcheckdesi | glowbawaal |
| 17 | Travel | ghumobawaal | roadtripbhaukaal |
| 18 | Home and finds | addtocartbhai | cartkalesh, gharauradesi |
| 19 | Parenting | desiparentlore | none |
| 20 | Couples | situationshipdesi | redflagbhai |
| 21 | Mobile gaming | lobbykalesh | clutchbawaal |
| 22 | Esports | acebhaukaal | clutchauradesi |
| 23 | Cricket | dugoutbawaal | none |
| 24 | Football and other sports | ballknowledgebhai | footykalesh, goalbhaukaal |
| 25 | Cars and bikes | gaadibhaukaal | revkalesh, torqueauradesi |
| 26 | Spirituality | karmaloredaily | none |
| 27 | Animals and nature | **billikalesh (pilot, done)** | doggolore, pawbhaukaal |

The sign up email is always the primary handle at `musubi.si`, even when a backup handle is used. Suggested profile for karmaloredaily: name "Karma Lore Daily", bio "Daily lessons on karma, dharma and life 🕉️ / Stories from the Gita, saints and everyday life".

## Next steps, in order

1. **Settle the open questions** below with Prateek. The billikalesh clip source decides the intake for the pilot.
2. **Write the implementation plan** from `design.md` (superpowers:writing-plans), pilot scope only.
3. **Create the new Meta app** for the pages, separate from the marketplace app (id 1074493771960727), with Instagram Login. Add billikalesh as an Instagram tester; Prateek accepts the invite in the account. The app needs a public privacy policy URL and a data deletion path, which can be static pages.
4. **AWS**: an EC2 instance, an S3 bucket and IAM in `ap-south-1`; Bedrock (Claude) and Polly access. Confirm the credits cover Bedrock, and when they expire.
5. **Build the pilot** (design §5, §6), then run billikalesh daily for 2 weeks.
6. **Check the result:** if billikalesh's reach from non followers stays near zero, the AI original layer isn't counting as original, and that needs fixing before adding more pages.

## Open

- **Where billikalesh's clips come from** (design §9): animal creators who agree to clipping, Creative Commons (CC BY) YouTube videos, stock footage (Pexels or Pixabay) with fact voiceover, or a mix.
- **Builder check results**: a reviewer read `design.md` as a builder; its questions are appended below when they land.
- **Repository**: this folder isn't a git repo yet. Plan: a new private repo in the musubiclip GitHub org (`env -u GITHUB_TOKEN gh ...` for that org).

## Rules that came out of the planning (don't relitigate)

- Pages are owned openly. No proxies, VPNs per account, antidetect browsers, or account linking in one Accounts Center. No automated follow, like, comment or DM.
- Every clip gets an original layer. One clip goes to one page. Run the copyright check and strip music.
- A publish error 2207050 or 2207051 pauses that page.
- Keep the pages away from the marketplace: not the musubi-platform repo, not its Meta app, not its WhatsApp number, and not the `musubi_clip` Instagram account (it's saved in the same Chrome as billikalesh; keep the pages in their own browser profile).
- Prateek wants questions asked through the AskUserQuestion tool, one decision at a time, with a recommended option.
