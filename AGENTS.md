# AGENTS guide

This file is the **table of contents** for repository-local knowledge used by coding agents.

## Working contract
- Keep changes deterministic, explicit, and environment-configurable.
- Prefer small, focused pull requests with clear acceptance criteria.
- Update documentation in `docs/` whenever behavior or operating assumptions change.
- Run repository checks before proposing changes.

## Where to look first
1. `README.md` for deployment scope and high-level layout.
2. `ARCHITECTURE.md` for domain and dependency boundaries.
3. `docs/index.md` for detailed operational and product documentation.
4. `docs/QUALITY_SCORE.md` for current quality targets and debt priorities.
5. `docs/exec-plans/` for active and completed implementation plans.

## Domain map
- Docker and runtime topology: `docker-compose.yml`, `docker/`, `startup/`.
- Web plugins: `omeroweb_*` packages and `omero_plugin_common/` shared utilities.
- Operations and monitoring: `docs/operations/`, service health endpoints, maintenance scripts.

## Knowledge maintenance
- Keep knowledge in version control; avoid undocumented decisions in external tools.
- Add cross-links in `docs/index.md` when introducing new top-level docs.
- Validate docs structure with `python3 tools/lint_docs_structure.py`.
