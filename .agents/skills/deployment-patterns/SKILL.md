---
name: deployment-patterns
description: Deployment and rollout guidance for this repo's Dockerized OMERO platform, with emphasis on env contracts and update safety.
origin: ECC v1.10.0 adapted for OMERO Docker Extended
upstream: third_party/ecc-v1.10.0/skills/deployment-patterns/SKILL.md
---

# Deployment Patterns

Use this skill when changing installation, update, rollout, health, or service topology behavior.

## Upstream baseline

Start from `third_party/ecc-v1.10.0/skills/deployment-patterns/SKILL.md` for generic deployment checklists and rollout patterns.

## Repo overlay

- This repo is a single integrated Docker Compose platform, not a generic cloud microservice stack.
- Favor explicit update safety over clever rollout logic; check `installation/`, `github_pull_project_bash_example`, and the deployment docs first.
- Keep configuration in `env/*_example.env` and `installation_paths_example.env`, not in workflow or compose defaults.
- Preserve health checks, image pinning, and no-new-privileges hardening.
- Update deployment docs whenever runtime assumptions change.
