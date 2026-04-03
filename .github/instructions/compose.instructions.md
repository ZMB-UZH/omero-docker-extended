---
applyTo: "docker-compose.yml"
---

# Docker Compose instructions

- Keep `docker-compose.yml` minimal and environment-driven.
- Do not add build args, secret defaults, or inline version defaults that belong in `env/*_example.env` or Dockerfile `ARG` defaults.
- Every service must preserve health checks and `security_opt: no-new-privileges:true`.
- Use `.agents/skills/docker-patterns/`, `.agents/skills/deployment-patterns/`, and `.agents/skills/env-contract-reviewer/` before changing service wiring.
