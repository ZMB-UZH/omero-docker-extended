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

- Read `AGENTS.md` first, then `docs/reference/ai-agent-context-routing.md`. Do not dump the whole docs tree into context.
- Use `rg` to find the narrow file set before opening files.
- Use an iterative retrieval loop: broad search, evaluate, refine once or twice, then stop when the context is good enough.
- Follow the routing doc's numeric caps. They are CI-validated by `python3 tools/lint_docs_structure.py`.
- Open at most 4 task-specific files in the first pass: one domain doc, one implementation file, one nearest test module or suite, and one matching skill.
- Run at most 2 refine loops before you either name the edit target or escalate.
- Add at most 3 more files per escalation round: one additional domain doc, one adjacent implementation file, and one more confirming test module.
- If you have opened 8 task-specific files without naming the edit target and verification lane, stop and summarize before reading more.
- Prefer the nearest skill in `.agents/skills/` over re-deriving a workflow from scratch.
- Summarize long docs once and reuse the summary instead of reopening the same file repeatedly.
- Load one domain doc, one nearest test module, and one split verification lane before broadening scope.
- For verification, run only the relevant split test lanes, not every suite by default.
- Keep platform-native adapter files concise so they stay cheap to load on every session.
