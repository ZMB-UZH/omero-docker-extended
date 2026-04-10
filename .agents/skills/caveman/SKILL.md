---
name: caveman
description: Lower output token usage on demand without sacrificing technical accuracy, safety, or repo-specific clarity.
origin: repo-local caveman integration adapted from caveman v1.3.5 for OMERO Docker Extended
---

# Caveman

Use this skill only when the user explicitly asks for lower-token replies, terse mode, `$caveman`, or "less tokens".

## Route first

- Keep `AGENTS.md`, `docs/reference/ai-agent-context-routing.md`, and `docs/reference/ai-agent-skills.md` as the primary contract.
- Use `context-budget` to cut input/context cost first; use `caveman` to cut output tokens second.
- The upstream reference lives in `third_party/caveman-v1.3.5/skills/caveman/SKILL.md`.

## Compression rules

- Compression never outranks correctness, safety, or precise dates.
- Default to lite compression; use heavier compression only if the user asks for it.
- Keep code, commands, file references, exact errors, and verification results normal and lossless.
- Drop compression and return to normal detail for destructive actions, security guidance, migrations, multi-step runbooks, incident analysis, or unresolved ambiguity.
- If the user seems confused, explain clearly first and resume terse mode only after the risky part is resolved.

## Good outcome

Lower token usage, same technical substance, no repo degradation.
