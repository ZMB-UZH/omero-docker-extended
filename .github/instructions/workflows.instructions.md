---
applyTo: ".github/workflows/*.yml"
---

# GitHub Actions workflow instructions

- Do not modify workflows unless the task explicitly requires it.
- Refresh action versions from official GitHub releases or tags before changing pins, and pin by full commit SHA.
- Consult `docs/operations/code-scanning.md` and `docs/reference/ai-agent-security-prevention-playbook.md` before changing security-relevant workflow logic.
- This repository's `tests.yml` uses the GitHub Actions environment `ci-coverage`. Pushes to `main` therefore create GitHub deployment records for that CI environment even when no runtime deployment occurred.
