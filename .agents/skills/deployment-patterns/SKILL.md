---
name: deployment-patterns
description: Deployment and rollout guidance for this repo's dockerized OMERO platform, with emphasis on env contracts and update safety.
origin: ECC v2.0.0 adapted for OMERO Docker Extended
upstream: third_party/ecc-v2.0.0/skills/deployment-patterns/SKILL.md
---

# Deployment Patterns

Use this skill when changing installation, update, rollout, health, or service topology behavior.

## Upstream baseline

Start from `third_party/ecc-v2.0.0/skills/deployment-patterns/SKILL.md` for generic deployment checklists and rollout patterns.

## Repo overlay

- This repo is a single integrated docker compose platform, not a generic cloud microservice stack.
- Favor explicit update safety over clever rollout logic; check `installation/`, `installation/github_pull_project_bash`, and the deployment docs first.
- Keep configuration in `env/*_example.env` and `installation_paths_example.env`, not in workflow or compose defaults.
- Preserve health checks, image pinning, and no-new-privileges hardening.
- Keep the standard installer and `easy_installation_script.sh`
  interchangeable: the easy path must use `PREBUILT_IMAGE_MODE=require`, load
  verified release-built images, preserve the same env/data/path handling, and
  fail instead of switching to a local build when the carrier cannot be used.
- Update deployment docs whenever runtime assumptions change.
