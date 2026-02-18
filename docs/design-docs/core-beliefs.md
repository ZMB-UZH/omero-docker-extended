# Core Beliefs

Operating principles that guide all decisions in this repository.

1. **Repository-local knowledge is the system of record.** Decisions made in Slack, email, or meetings do not exist for future developers or AI agents unless they are captured in versioned files. If it matters, it belongs in `docs/`.

2. **Short navigation docs over monolithic instructions.** `AGENTS.md` is a table of contents, not an encyclopedia. `docs/index.md` is a navigation hub with cross-links. Deep content lives in domain-specific documents. When everything is "important," nothing is.

3. **Mechanical checks enforce structure and freshness.** The documentation structure is validated by `tools/lint_docs_structure.py` and CI. Required files, cross-links, and index entries are checked automatically. Drift is caught before merge.

4. **Architectural boundaries must be explicit and verifiable.** Plugin packages depend on `omero_plugin_common`, never the reverse. Plugins do not depend on each other. Startup scripts consume only environment variables. These rules are documented in `ARCHITECTURE.md` and can be verified by inspection.

5. **Configuration is environment-driven with zero hard-coded values.** All paths, credentials, endpoints, and tuning parameters come from `env/*.env` files. Error messages reference the correct env file and variable name. This makes the system deployable in any environment without code changes.

6. **Pin everything.** Docker images, Python packages, and external dependencies use explicit version tags. `:latest` and unpinned ranges are never used. Dependabot monitors for updates weekly.

7. **Deterministic startup.** Bootstrap scripts are idempotent, fail fast with clear messages, and never produce different results on re-run. Health checks enforce startup ordering across services.

8. **Agent legibility.** The repository is structured so that an AI agent (or a new human engineer) can navigate from `AGENTS.md` to any relevant file in two hops. Context is organized for progressive disclosure, not front-loaded as a wall of text.
