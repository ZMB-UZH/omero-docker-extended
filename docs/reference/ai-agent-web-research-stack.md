# AI Agent Web Research Stack

This reference captures the safe, tool-agnostic public-web research pattern these repos expect as of `2026-04-12`.

## Core Pattern

1. Search the repo, local docs, and user-provided links first.
2. Prefer official docs, release notes, source repositories, standards pages, and issue trackers.
3. Use bounded public-web discovery to find the smallest set of relevant sources.
4. Extract only the needed text or structured data from each source.
5. Escalate to a real browser only when direct fetch or DOM extraction is insufficient.
6. Audit source quality, dates, and contradictions before making claims.
7. Reuse sessions, cache results, and back off instead of hammering a site.

## Safe Defaults

- Bias toward free, built-in, open-source, or self-hostable tooling when the task allows.
- Prefer deterministic browser control and repeatable extraction over one-off manual wandering.
- Treat browser automation as a fallback, not the first move.
- Keep URLs, dates, versions, and access times with your notes so later answers stay traceable.

## Maintained Tool Families

These are examples of current, widely used public-web research building blocks. They are references, not hard dependencies for the repo.

| Capability | Preferred pattern | Maintained examples |
| --- | --- | --- |
| Discovery and search | official site search, repo search, then public-web search | Firecrawl, Jina search, GitHub search, docs-site search |
| Direct extraction | raw markdown, HTML, API, or structured endpoint first | Firecrawl extract/scrape, Jina Reader, `curl`/fetch-style retrieval |
| Deterministic browser fallback | one reusable session with explicit actions and DOM/network inspection | Playwright, Chrome DevTools MCP, Browser Use |
| Larger bounded crawls | only when a justified multi-page crawl is necessary | Crawl4AI, Crawlee/Apify |

## Hard Boundaries

- Do not bypass CAPTCHAs, paywalls, rate limits, bot checks, geo blocks, login walls, or access controls.
- Do not rotate identities, scrape against explicit denial signals, or simulate evasive traffic.
- Do not paste PATs, passwords, cookies, or internal-only URLs into public-web tools.
- If a site requires authentication or human verification, stop and ask for a permitted session or alternate source.

## Official References Reviewed

- Firecrawl docs and repository
- Browser Use docs and repository
- Playwright docs and repository
- Chrome DevTools MCP blog announcement and repository
- Jina Reader repository
- Crawl4AI repository
- Crawlee/Apify documentation and repository

Use the repo-local skills `web-discovery`, `site-extract`, `browser-fallback`, `source-audit`, and `compliance-and-rate-limit` to apply this stack in small, auditable steps.
