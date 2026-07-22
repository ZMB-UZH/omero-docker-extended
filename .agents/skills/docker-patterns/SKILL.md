---
name: docker-patterns
description: docker and Compose patterns for this repo's multi-container OMERO runtime, startup scripts, and hardening rules.
origin: ECC v2.0.0 adapted for OMERO Docker Extended
upstream: third_party/ecc-v2.0.0/skills/docker-patterns/SKILL.md
---

# Docker Patterns

Use this skill when changing Dockerfiles, `docker-compose.yml`, startup scripts, or service-to-service wiring.

## Upstream baseline

Start from `third_party/ecc-v2.0.0/skills/docker-patterns/SKILL.md` for generic container and Compose patterns.

## Repo overlay

- This repo pins images and versions; do not introduce `:latest`.
- Keep env and version defaults in `env/*_example.env` or Dockerfile `ARG` defaults, not Compose sprawl.
- Preserve service health checks and `security_opt: no-new-privileges:true`.
- Treat startup scripts as runtime contracts that must stay environment-driven and shell-only.
- The prebuilt carrier is a scratch data image. Do not add an OS base, shell,
  package manager, healthcheck command, or post-copy permission mutation that
  duplicates the large runtime archive layer.
- Release-runner storage cleanup must be derived from the rendered Compose
  image list. Do not hard-code service images or prune required image IDs.
- Pause for explicit confirmation of the exact release and Docker tags before
  release work; never infer or auto-increment a version. Carry the matching
  human-readable `CHANGELOG.md` notes and OCI
  metadata in the carrier image only after automated disclosure validation and
  human public-safety review; reject credentials, identities, host details,
  private infrastructure, findings, vulnerability mechanics, and
  exploit-enabling detail.
- Keep release notes curated and concise: include only notable operator or user
  impact, compatibility or required upgrade actions, and a brief verification
  summary; omit commit-by-commit detail, internal workflow or governance
  narration, agent activity, and exhaustive test inventories.
- Never delete a pre-existing Docker image or tag without fresh approval naming
  that one object. Approval for a replacement, prior run, or same version does
  not carry forward.
- For live runtime probing, follow the Loki-first and service-user rules in `AGENTS.md`.
