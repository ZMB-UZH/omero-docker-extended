---
name: compliance-and-rate-limit
description: Keep public-web research compliant, bounded, and efficient through rule checks, caching, and backoff instead of evasive scraping.
---

# Compliance And Rate Limit

Use this skill for repeated requests, bounded crawls, or any workflow that could create avoidable load or policy risk.

## Workflow

1. Prefer official APIs, feeds, sitemaps, or documented exports before scraping.
2. Check the site's published rules or technical signals when they materially affect the task.
3. Cache fetched pages and reuse sessions instead of re-requesting the same content.
4. Use bounded concurrency, small page sets, and exponential backoff.
5. If the site signals blocking or restricted access, stop escalating and switch to a permitted source or human handoff.

## Rules

- No bypass or evasion of CAPTCHAs, bot detection, rate limits, or access controls.
- Do not leak secrets, session tokens, or internal-only URLs into external tools.
- Collect only the data needed for the task.
- If a task requires authenticated access, ask the user for a permitted workflow instead of improvising one.

## Output

- The chosen collection boundary, pacing assumptions, and any blockers.
- A clear note when the safe answer is to stop rather than push harder.

## Read next

- `docs/reference/ai-agent-web-research-stack.md`
- `web-discovery`, `site-extract`, `browser-fallback`, and `source-audit`
