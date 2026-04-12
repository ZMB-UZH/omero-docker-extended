---
name: web-discovery
description: Plan and run current public-web discovery for docs, releases, issues, and community evidence without guessing or over-browsing.
---

# Web Discovery

Use this skill when the user needs current public-web research, release/status checks, recommendations, or evidence from multiple sites.

## Workflow

1. Search the repo, provided links, and known local docs first.
2. Prefer official docs, release notes, source repositories, standards pages, and issue trackers before secondary coverage.
3. Split broad questions into small queries with exact product names, versions, dates, errors, and domain filters where possible.
4. Stop widening scope once the answer is supported by enough primary evidence.
5. Hand the gathered sources to `source-audit` before making strong claims or recommendations.

## Rules

- Separate official statements, maintainer comments, benchmarks, and user anecdotes.
- Use exact dates for unstable facts.
- Do not paste PATs, passwords, internal URLs, or private repo details into external search tools.
- For high-stakes or version-sensitive facts, keep the search set biased toward primary sources.

## Output

- A short evidence list with source, date, and why it matters.
- Explicit labels for confirmed facts, reasoned inferences, and remaining gaps.

## Read next

- `docs/reference/ai-agent-web-research-stack.md`
- `site-extract`, `browser-fallback`, `source-audit`, and `compliance-and-rate-limit` as needed
