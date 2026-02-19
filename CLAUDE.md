# Claude Code instructions

Project-specific instructions for Claude Code sessions working on this repository.

## Repository identity

This is **OMERO Docker Extended**: a production containerized OMERO imaging platform with 4 custom Django web plugins, a full monitoring stack, and automated database maintenance. See `README.md` for the complete service topology and `ARCHITECTURE.md` for layer model and dependency rules.

## Navigation

Start with `AGENTS.md` for the full domain map. Key entry points:

- Service orchestration: `docker-compose.yml`
- Plugin code: `omeroweb_omp_plugin/`, `omeroweb_upload/`, `omeroweb_admin_tools/`, `omeroweb_imaris_connector/`
- Shared library: `omero_plugin_common/`
- Configuration: `env/*.env` files, `installation_paths.env`
- Startup logic: `startup/*.sh`
- Image builds: `docker/*.Dockerfile`
- Monitoring config: `monitoring/`
- Documentation: `docs/index.md` (full index)

## Development rules

### Configuration
- All configuration is environment-driven via `env/*.env` files.
- Treat repository-tracked `*_example*` files as canonical templates for expected runtime shape and keys.
- Assume corresponding non-example files are provisioned by the sysadmin and match template structure unless explicitly documented otherwise.
- Use `omero_plugin_common.env_utils` for typed env var access in Python code.
- Never hard-code paths, credentials, hostnames, or ports.
- Reference the correct `env_file` constant (`ENV_FILE_OMEROWEB`, `ENV_FILE_OMERO_CELERY`, etc.) in error messages.

### Plugin architecture
- Plugins depend on `omero_plugin_common`, never the reverse.
- Plugins do not depend on each other.
- Follow the existing layout: `apps.py`, `config.py`, `urls.py`, `views/`, `services/`, `strings/`, `templates/`, `static/`, `tests/`.
- Each plugin's `AppConfig.ready()` calls `configure_omero_gateway_logging()`.
- Error and message strings live in `strings/errors.py` and `strings/messages.py` as functions, not bare strings.
- Views import from `omero_plugin_common.request_utils` for JSON parsing and username resolution.

### Docker and infrastructure
- Pin all image tags in `docker-compose.yml` and Dockerfiles. Never use `:latest`.
- Every service must have a `healthcheck:` block and `security_opt: no-new-privileges:true`.
- Startup scripts must only consume environment variables; they must not import Python modules.
- The `omeroweb` container runs two processes via supervisord (OMERO.web + Celery worker).

### Security
- Keep secrets out of source control. The `env/` directory is gitignored except for `*_example.env` templates.
- Treat plugin input as untrusted; validate at system boundaries.
- Use OMERO permissions checks for data access.
- Do not expose monitoring interfaces without authentication.

### Documentation
- Update docs when behavior or operating assumptions change.
- Run `python3 tools/lint_docs_structure.py` to validate docs structure before committing.
- Required files and cross-links are enforced by CI (`.github/workflows/docs-knowledge-base.yml`).
- Add cross-links in `docs/index.md` when introducing new documents.
- Keep `README.md`, `AGENTS.md`, `ARCHITECTURE.md`, and `CLAUDE.md` at repository root; everything else under `docs/`.

## Common tasks

### Adding a new environment variable
1. Add it to the relevant `env/*_example.env` template with a descriptive comment.
2. Load it in the plugin's `config.py` using the appropriate `omero_plugin_common.env_utils` function (`get_env`, `get_int_env`, `get_bool_env`, etc.).
3. Document it in `docs/deployment/configuration.md`.

### Adding a new plugin route
1. Add the URL pattern in the plugin's `urls.py`.
2. Create the view function in `views/`.
3. Update `docs/plugins/<plugin-name>.md` and `docs/reference/service-endpoints.md`.

### Modifying Docker services
1. Edit `docker-compose.yml` or the relevant Dockerfile in `docker/`.
2. Ensure health checks are present and correct.
3. Update `docs/architecture/system-overview.md` if the service topology changes.

### Modifying monitoring
1. Edit the relevant config in `monitoring/`.
2. Update `docs/operations/monitoring.md`.
3. If adding new Prometheus targets, update `monitoring/prometheus/prometheus.yml`.
4. If adding new dashboards, place JSON in `monitoring/grafana/dashboards/`.

## Testing

```bash
# Run docs structure validation
python3 tools/lint_docs_structure.py

# Run docs lint tests
python3 -m unittest -v tests/test_lint_docs_structure.py

# Run plugin unit tests (example)
python3 -m pytest omeroweb_imaris_connector/tests/ -v
python3 -m pytest omero_plugin_common/tests/ -v
```

## Build and deploy

```bash
# Build all images
docker compose --env-file installation_paths.env build

# Start all services
docker compose --env-file installation_paths.env up -d

# Check service health
docker compose --env-file installation_paths.env ps

# View logs for a service
docker compose --env-file installation_paths.env logs -f omeroweb
```
