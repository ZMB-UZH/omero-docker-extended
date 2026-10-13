---
name: browser-fallback
description: Diagnose interactive page behavior without replacing mandatory Crawl4AI source reading.
origin: repo-local web research workflow
---

# Browser Fallback

Use this skill to diagnose JS-heavy, stateful or lazy-loaded page behavior.
It is not an alternative reader for mandatory public-web research.

## Workflow

1. Preserve the failed Crawl4AI receipt and identify the diagnostic question.
   Pause dependent research; browser output cannot replace the required crawl.
2. Use the harness-provided browser tool or the most deterministic browser stack available.
3. Reuse one session per site, inspect DOM and network behavior before adding extra actions, and record the exact final URL.
4. Capture the minimum reproducible navigation steps, selectors, and visible result state.
5. Restore Crawl4AI extraction and retain a valid native capture before using
   page content as evidence; apply `source-audit` to that capture.

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
