---
applyTo: ".github/workflows/*.yml"
---

# GitHub Actions workflow instructions

- Do not modify workflows unless the task explicitly requires it.
- Refresh action versions from official GitHub releases or tags before changing pins, and pin by full commit SHA.
- Consult `docs/operations/code-scanning.md` and `docs/reference/ai-agent-security-prevention-playbook.md` before changing security-relevant workflow logic.
- Keep workflow runbooks and agent guidance default-branch-aware; do not tell agents to create branches or draft PRs for routine workflow checks.
- No workflow in this repository may create GitHub deployment records.
- Do not add job-level `environment` blocks; GitHub Actions environments create
  deployment records. Keep release credentials in repository secrets with the
  documented names instead.
