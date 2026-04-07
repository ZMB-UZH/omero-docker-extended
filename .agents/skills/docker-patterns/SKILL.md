---
name: docker-patterns
description: Docker and Compose patterns for this repo's multi-container OMERO runtime, startup scripts, and hardening rules.
origin: ECC v1.10.0 adapted for OMERO Docker Extended
upstream: third_party/ecc-v1.10.0/skills/docker-patterns/SKILL.md
---

# Docker Patterns

Use this skill when changing Dockerfiles, `docker-compose.yml`, startup scripts, or service-to-service wiring.

## Upstream baseline

Start from `third_party/ecc-v1.10.0/skills/docker-patterns/SKILL.md` for generic container and Compose patterns.

## Repo overlay

- This repo pins images and versions; do not introduce `:latest`.
- Keep env and version defaults in `env/*_example.env` or Dockerfile `ARG` defaults, not Compose sprawl.
- Preserve service health checks and `security_opt: no-new-privileges:true`.
- Treat startup scripts as runtime contracts that must stay environment-driven and shell-only.
- For live runtime probing, follow the Loki-first and service-user rules in `AGENTS.md`.
