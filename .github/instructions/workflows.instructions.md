---
applyTo: ".github/workflows/*.yml"
---

# GitHub Actions workflow instructions

- Do not modify workflows unless the task explicitly requires it.
- Refresh action versions from official GitHub releases or tags before changing pins, and pin by full commit SHA.
- Consult `docs/operations/code-scanning.md` and `docs/reference/ai-agent-security-prevention-playbook.md` before changing security-relevant workflow logic.
- Keep workflow runbooks and agent guidance default-branch-aware; do not tell agents to create branches or draft PRs for routine workflow checks.
- No workflow in this repository may create GitHub deployment records.
- The only workflow that may use the `dockerhub-release` environment is
  `release-prebuilt-carrier.yml`, and that job must keep `deployment: false` so
  environment secrets can be protected without creating GitHub deployment
  records.
