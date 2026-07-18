---
name: caveman
description: Lower output token usage on demand for all AI Agents without sacrificing technical accuracy, safety, or repo-specific clarity.
origin: repo-local caveman overlay adapted from caveman v1.9.1 for OMERO Docker Extended
---

# caveman

Use this skill only when the user explicitly asks for lower-token replies, terse mode, `$caveman`, or "less tokens".

## Route first

- Keep `AGENTS.md`, `docs/reference/ai-agent-context-routing.md`, and `docs/reference/ai-agent-skills.md` as the primary contract.
- Use `context-budget` to cut input/context cost first; use `caveman` to cut output tokens second.
- The upstream reference lives in `third_party/caveman-v1.9.1/skills/caveman/SKILL.md`. All supported agents use this shared overlay.
- `caveman` is for internal AI reply/prompting only. Never use caveman prose in repo docs, comments, docstrings, commit messages, or user-facing copy. It changes response style only and must not change context selection, tool choice, verification scope, or clarification decisions.
- This repo does not import upstream hooks, plugin auto-loading, `.codex` hook config, natural-language auto-activation, `CAVEMAN_DEFAULT_MODE`, `off`, `caveman-help`, `/compress` rewriting, stats/statusline scripts, `caveman-shrink`, `caveman-init`, cavecrew subagents, or smart-installer side effects.

## Compression rules

- Compression never outranks correctness, safety, or precise dates.
- Start at lite compression here; use heavier compression only if the user asks for it.
- Keep code, commands, file references, exact errors, and verification results normal and lossless.
- Preserve the user's dominant language; compress the style, not the language. Do not invent prose abbreviations or causal arrows.
- Preserve exact technical text: never abbreviate code symbols, function names, API names, paths, URLs, error strings, Typst, LaTeX, or code.
- Do not narrate the mode, refer to the agent or style, add decorative tables or emoji, or dump long raw logs unless the user asks for them.
- If terse wording would hide uncertainty, name the uncertainty normally instead.
- Drop compression and return to normal detail for destructive actions, security guidance, migrations, multi-step runbooks, incident analysis, unresolved ambiguity, or any case where compression itself makes ordering or meaning unclear.

## Good outcome

Lower token usage, same technical substance, no repo degradation.
