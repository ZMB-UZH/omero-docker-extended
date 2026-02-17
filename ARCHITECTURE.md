# Architecture Overview

## System intent
OMERO Docker Extended packages OMERO server components, OMERO.web plugins, background workers, and observability services into a reproducible containerized deployment.

## Layer model
1. **Infrastructure layer** (`docker/`, `docker-compose.yml`, `env/`): image build/runtime contracts and service wiring.
2. **Runtime bootstrap layer** (`startup/`, `supervisord.conf`): deterministic startup and lifecycle behavior.
3. **Application layer** (`omeroweb_*`, `omero_plugin_common/`): plugin business logic and integration points.
4. **Operations layer** (`docs/operations/`, maintenance scripts): monitoring, maintenance, and reliability practices.

## Dependency boundaries
- Plugin packages depend on `omero_plugin_common`, never the reverse.
- Startup scripts must consume environment-provided configuration only.
- Documentation is the source of truth for runtime behavior and operational procedures.

## Quality gates
- Documentation structure and cross-links are enforced by `tools/lint_docs_structure.py`.
- Every new architectural decision should be captured under `docs/design-docs/`.
