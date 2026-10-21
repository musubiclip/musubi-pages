# Musubi Pages

Internal tool that runs Musubi's niche Instagram pages: cut clips, add an original layer, review, publish through the Instagram API, track views.

Start with `HANDOFF.md` (state, next steps, the 27 pages), then `design.md` (what to build and why). `research/` holds the sources behind the design.

- Separate from musubi-platform. Never touch the marketplace's code, Meta app, WhatsApp number or the `musubi_clip` Instagram account from here.
- Python app on AWS `ap-south-1`. The clip engine is the musubi-clips skill (`~/.claude/skills/musubi-clips`).
- No engagement automation, ever. No proxies or anything that hides who owns the pages.
- Never handle Instagram passwords or 2FA secrets. Those live in Bitwarden, entered by a person.
