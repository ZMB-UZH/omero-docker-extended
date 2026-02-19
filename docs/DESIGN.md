# Design Principles

Guiding principles for all code, configuration, and infrastructure decisions in this repository.

## Explicit contracts

- Prefer explicit contracts for configuration, startup order, and service dependencies.
- Every service dependency is declared in `docker-compose.yml` with `depends_on:` and health check conditions.
- Environment variables are the only configuration surface. Use `omero_plugin_common.env_utils` with typed getters that produce actionable error messages referencing the correct env file.
- Startup scripts fail fast with clear error messages when required preconditions are missing.

## Modularity and separation

- Keep plugin logic modular with clear separation between request handling (`views/`), business logic (`services/`), and external service integration (`services/omero/`).
- Error messages and user-facing strings live in dedicated `strings/` modules as functions, not inline literals.
- Shared utilities live in `omero_plugin_common/`. Plugin packages depend on it, never the reverse. Plugins do not depend on each other.

## Determinism and reproducibility

- Preserve deterministic behavior across environments by requiring explicit environment variables and pinned versions.
- Pin all Docker image tags and Python package versions. Never use `:latest` or unpinned ranges.
- Bootstrap scripts are idempotent: re-running them produces the same result.
- PostgreSQL mount paths use a `pgdata` subdirectory to avoid ext4 `lost+found` issues.

## Environment-driven configuration

- All paths, credentials, endpoints, and tuning parameters come from `env/*.env` files and `installation_paths.env`.
- No Python code or shell script may contain hard-coded hostnames, ports, or file paths.
- Plugin `config.py` modules centralize all env var access for their package.

## Progressive disclosure in documentation

- `AGENTS.md` is a short table of contents pointing to deeper sources. It is not an encyclopedia.
- `docs/index.md` is the full navigation hub with cross-links to every document.
- Deep technical detail lives in domain-specific docs, not in top-level files.
- Documentation structure is mechanically enforced by `tools/lint_docs_structure.py` and CI.
