---
applyTo: ".github/workflows/*.yml"
---

# GitHub Actions workflow instructions

- Do not modify workflows unless the task explicitly requires it.
- Refresh action versions from official GitHub releases or tags before changing pins, and pin by full commit SHA.
- Consult `docs/operations/code-scanning.md` and `docs/reference/ai-agent-security-prevention-playbook.md` before changing security-relevant workflow logic.
- Keep workflow runbooks and agent guidance default-branch-aware; do not tell agents to create branches or draft PRs for routine workflow checks.
- Before dispatching any release workflow, pause for explicit user confirmation of the exact GitHub release tag and Docker repository/tag. Workflows must require an explicit version, must not infer or auto-increment it, and must fail when the matching human-readable `CHANGELOG.md` section is absent.
  They must also require automated disclosure validation and explicit human public-safety review; public notes must reject credentials, personal or host-specific information, private infrastructure, findings, vulnerability mechanics, and exploit-enabling detail.
- Gate deletion of an existing GitHub release, Git tag, and Docker tag behind three separate fresh per-object confirmations. Earlier, blanket, same-version, replace, or recreate permission never carries forward to another deletion or run.
- No workflow in this repository may create GitHub deployment records.
- Do not add job-level `environment` blocks; GitHub Actions environments create
  deployment records. Keep release credentials in repository secrets with the
  documented names instead.
- If Zizmor flags `secrets-outside-env` for the manual release workflow, keep
  the ignore comment on the exact Docker Hub secret reference and keep the
  explanation tied to the no-deployment-record policy. Do not disable the audit
  globally and do not add a workflow environment to satisfy the scanner.
