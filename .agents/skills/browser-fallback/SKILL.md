---
name: browser-fallback
description: Use a deterministic browser workflow only when direct fetch or extraction is insufficient for a public-web task.
---

# Browser Fallback

Use this skill when static fetches fail because a page is JS-heavy, stateful, lazy-loaded, or otherwise not inspectable enough without a real browser session.

## Workflow

1. Confirm that repo search, direct fetch, and `site-extract` are insufficient first.
2. Use the harness-provided browser tool or the most deterministic browser stack available.
3. Reuse one session per site, inspect DOM and network behavior before adding extra actions, and record the exact final URL.
4. Capture the minimum reproducible navigation steps, selectors, and visible result state.
5. Once the data is visible, hand the content back to `site-extract` and `source-audit`.

## Stop Rules

- Do not bypass CAPTCHAs, paywalls, rate limits, bot checks, geo blocks, or access controls.
- Do not brute-force forms, rotate identities, or simulate evasive traffic.
- If login or a human challenge is required, stop and ask for a manual session, a permitted export, or an alternate source.
- Avoid destructive actions, account changes, or purchases.

## Good Defaults

- Prefer deterministic Playwright/CDP-style actions over vague browsing.
- Reuse the same browser tab/session when iterating on one site.
- Keep notes precise enough that another agent can replay the path.

## Read next

- `docs/reference/ai-agent-web-research-stack.md`
- `site-extract`, `source-audit`, and `compliance-and-rate-limit`
