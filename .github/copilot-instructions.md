# GitHub Copilot instructions

Read [AGENTS.md](../AGENTS.md) before work; it is the mandatory shared policy.
Do not load other adapters or repeat their policy. Read task contracts only at
the triggers in AGENTS. The .agents/skills/ overlays are authoritative:
CocoIndex for broad semantic routing, caveman lite for lower-token internal AI
communication. Public text stays normal prose. Safety and verification are
unchanged; no separate agent session or implicit Codex Security scan.

Use path-specific rules only for touched files. The catalog at
`docs/reference/ai-agent-skills.md` is for discovery, not a startup reading list.

Load `.github/instructions/*.instructions.md` only for matching paths.
