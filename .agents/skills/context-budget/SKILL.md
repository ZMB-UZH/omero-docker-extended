---
name: context-budget
description: Keep agent context small and high-signal by routing into AGENTS, the nearest docs, and the narrowest correct test lanes.
origin: ECC v1.9.0 adapted for OMERO Docker Extended
upstream: third_party/ecc-v1.9.0/skills/context-budget/SKILL.md
---

# Context Budget

Use this skill when a task is getting broad, slow, or repetitive, or when the user explicitly wants lower token usage.

## Upstream baseline

Start from `third_party/ecc-v1.9.0/skills/context-budget/SKILL.md` for the generic context-audit mindset.

## Repo overlay

- Read `AGENTS.md` first, then one relevant domain doc. Do not dump the whole docs tree into context.
- Use `rg` to find the narrow file set before opening files.
- Prefer the nearest skill in `.agents/skills/` over re-deriving a workflow from scratch.
- Summarize long docs once and reuse the summary instead of reopening the same file repeatedly.
- For verification, run only the relevant split test lanes, not every suite by default.
- Keep platform-native adapter files concise so they stay cheap to load on every session.
