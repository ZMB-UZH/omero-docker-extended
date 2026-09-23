---
name: context-budget
description: Keep agent context small and high-signal by routing into AGENTS, the nearest docs, and the narrowest correct test lanes.
origin: ECC v2.0.0 adapted for OMERO Docker Extended
upstream: third_party/ecc-v2.0.0/skills/context-budget/SKILL.md
---

# Context Budget

Use this skill when a task is getting broad, slow, or repetitive, or when the user explicitly wants lower token usage.

## Upstream baseline

`third_party/ecc-v2.0.0/skills/context-budget/SKILL.md` is provenance. Load upstream detail only when this overlay lacks task-specific guidance.

## Fast route

- Read `AGENTS.md` once; use `docs/reference/ai-agent-context-routing.md` only for unknown task locations. Do not dump the whole docs tree into context.
- Broad navigation requires `cocoindex-code-search`; search the narrow file set with `rg` for exact symbols and confirm semantic hits in current source.
- Open at most 4 task-specific files in the first pass: one domain doc, one implementation file, one nearest test module or suite, and one matching skill.
- Run at most 2 refine loops before broadening scope.
- Add at most 3 more files per escalation round: one additional domain doc, one adjacent implementation file, and one more confirming test module.
- If you have opened 8 task-specific files without naming the edit target and verification lane, stop and summarize before reading more.

## Repo rules

- Keep agent context small and high-signal.
- Follow the routing doc's numeric caps; they are CI-validated by `python3 tools/lint_docs_structure.py`.
- Load one domain doc, one nearest test module, and one split verification lane before broadening.
- Summarize long docs once and reuse the summary instead of reopening the same file repeatedly.
- Apply `caveman` lite to internal notes by default. Keep evidence, negations, identifiers, approvals, and public prose lossless.
- Prefer filenames, line ranges, structured summaries, and counts over full dumps. Keep complete raw evidence locally; report clipping and inspect omitted failure details before diagnosing.
- Cache tool schemas and unchanged retrievals for the session. On handoff, retain decisions, changed paths, relevant source/runtime identities, checks, risks, and next action.
- Prefer the nearest skill in `.agents/skills/` over re-deriving a workflow from scratch.
- For verification, run only the relevant split test lanes, not every suite by default.
- Keep a verification ledger of successful commands and the relevant tree state; do not rerun an unchanged gate merely for reassurance.
- Invalidate only checks whose code, configuration, fixtures, dependencies, or runtime artifact changed.
- Run independent read-only checks in parallel when host resources permit; serialize builds and live mutations that share Docker, databases, or persistent storage.
- Run the full required matrix once against the final tree before commit/push. Budgets limit waste, never required reasoning, coverage, or review depth.
