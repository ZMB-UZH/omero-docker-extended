---
applyTo: ".github/workflows/*.yml"
---

# GitHub Actions workflow instructions

- Do not modify workflows unless the task explicitly requires it.
- Refresh action versions from official GitHub releases or tags before changing pins, and pin by full commit SHA.
- Consult `docs/operations/code-scanning.md` and `docs/reference/ai-agent-security-prevention-playbook.md` before changing security-relevant workflow logic.
- Keep workflow runbooks and agent guidance default-branch-aware; do not tell agents to create branches or draft PRs for routine workflow checks.
- Do not bind pure CI jobs to GitHub Actions environments unless you intentionally want deployment records from GitHub Actions.
