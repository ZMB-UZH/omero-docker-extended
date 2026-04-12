---
name: site-extract
description: Extract the smallest useful amount of text or structured data from a known public page before falling back to full browser automation.
origin: repo-local web research workflow
---

# Site Extract

Use this skill when the target page or docs site is already known and the task is to extract facts, structured fields, or bounded excerpts.

## Workflow

1. Prefer an official API, feed, raw markdown, or direct HTML fetch over a rendered page.
2. Extract only the sections needed for the task instead of dumping whole pages.
3. Keep the source URL, page title, publish/update date, and access date with the notes.
4. Normalize findings into concise bullets, tables, or JSON-shaped notes.
5. If the content depends on client-side rendering or interaction, switch to `browser-fallback`.

## Rules

- Prefer text or DOM extraction over screenshot-only reading.
- Preserve enough structure for later citation and verification.
- Do not copy long copyrighted passages when a short summary is enough.
- If the site exposes stable machine-readable fields, use those rather than re-parsing visible prose.

## Output

- Bounded structured notes tied to exact URLs.
- Missing fields or extraction blockers called out explicitly.

## Read next

- `docs/reference/ai-agent-web-research-stack.md`
- `browser-fallback` or `source-audit` when needed
