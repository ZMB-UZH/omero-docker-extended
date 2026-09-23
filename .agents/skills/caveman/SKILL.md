---
name: caveman
description: Mandatory lite compression for internal AI communication; preserve exact evidence, safety, and normal public prose.
origin: repo-local caveman overlay adapted from caveman v2.2.0 for OMERO Docker Extended
---

# caveman

Apply this skill by default in every task. Lower token usage is mandatory, not opt-in; use lite compression for internal AI communication only.

## Route first

- Keep `AGENTS.md` as the primary contract; use the context router only when the task location is unknown. Do not load the entire skill catalog.
- Use `context-budget` to cut input/context cost first and `caveman` second. All supported agents share this overlay; `third_party/caveman-v2.2.0/skills/caveman/SKILL.md` is provenance, not a required read.
- `caveman` is for internal AI reply/prompting only. Never use caveman prose in persisted text for other people: docs, comments, docstrings, commits, issues, pull requests, defect reports, messages, and user-facing copy always use normal prose. It changes response style only and must not change context selection, tool choice, verification scope, or clarification decisions.
- This repo does not import upstream hooks, plugin auto-loading, `.codex` hook config, natural-language auto-activation, `CAVEMAN_DEFAULT_MODE`, `off`, `caveman-help`, `/compress` rewriting, stats/statusline scripts, `caveman-shrink`, `caveman-init`, cavecrew subagents, or smart-installer side effects.

## Compression rules

- Compression never outranks correctness, safety, or precise dates. Start at lite compression; use heavier compression only when requested.
- Never remove `not`, `never`, `no`, `only`, or `except`; preserve numbers and units exactly. Do not add words, damage grammar, or switch languages to imitate terseness; use normal prose when it is not shorter and clearer.
- Keep code, commands, file references, exact errors, and verification results normal and lossless; never abbreviate code symbols, function names, API names, paths, URLs, Typst, or LaTeX.
- Follow an explicit reply-language instruction first; otherwise preserve the user's dominant language. Compress the style, not the language. Do not invent prose abbreviations or causal arrows.
- Do not narrate the mode, refer to the agent or style, add decorative tables or emoji, or dump long raw logs unless the user asks for them.
- Required progress updates and host-application collaboration rules remain in force; output compression cannot suppress them.
- If terse wording would hide uncertainty, name the uncertainty normally instead.
- Drop compression and return to normal detail for destructive actions, security guidance, migrations, multi-step runbooks, incident analysis, unresolved ambiguity, or any case where compression itself makes ordering or meaning unclear.

## Good outcome

Lower token usage, same technical substance, no repo degradation.
