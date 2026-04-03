---
applyTo: "**/*.sh"
---

# Shell and runtime instructions

- Startup and installation scripts must stay environment-driven. Do not inline site-specific paths or secrets.
- When touching bootstrap logic, check `startup/`, `installation/`, `installation_paths_example.env`, and the matching docs first.
- Use `.agents/skills/docker-patterns/`, `.agents/skills/deployment-patterns/`, `.agents/skills/env-contract-reviewer/`, and `.agents/skills/omero-runtime-verifier/` when relevant.
- Validate shell syntax with `bash -n` on changed scripts.
- Do not treat host-side Docker socket failures as proof that Docker is broken; follow the runtime procedure documented in `AGENTS.md`.
