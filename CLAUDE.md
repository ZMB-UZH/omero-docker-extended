# Claude Code instructions

Project-specific instructions for Claude Code sessions working on this repository.

## Repository identity

This is **OMERO Docker Extended**: a production containerized OMERO imaging platform with 4 custom Django web plugins, a full monitoring stack, and automated database maintenance. See `README.md` for the complete service topology and `ARCHITECTURE.md` for layer model and dependency rules.

## Navigation

Start with `AGENTS.md` for the full domain map. Key entry points:

- Service orchestration: `docker-compose.yml`
- Plugin code: `omeroweb_omp_plugin/`, `omeroweb_import/`, `omeroweb_admin_tools/`, `omeroweb_imaris_connector/`
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
- All environment variables and version pins go into the appropriate `env/*_example.env` file(s), not into `docker-compose.yml` or inline in scripts, unless absolutely necessary. Dockerfile `ARG` defaults are acceptable for build-time version pins (e.g. `ARG OMEZARR_READER_VERSION=0.6.0`), but `docker-compose.yml` must not carry redundant `args:` blocks or fallback defaults for values already defined elsewhere.
- Reference the correct `env_file` constant (`ENV_FILE_OMEROWEB`, `ENV_FILE_OMERO_CELERY`, etc.) in error messages.

### Plugin architecture
- Plugins depend on `omero_plugin_common`, never the reverse.
- Plugins do not depend on each other.
- Follow the existing layout: `apps.py`, `config.py`, `urls.py`, `views/`, `services/`, `strings/`, `templates/`, `static/`, `tests/`.
- Each plugin's `AppConfig.ready()` calls `configure_omero_gateway_logging()`.
- Error and message strings live in `strings/errors.py` and `strings/messages.py` as functions, not bare strings.
- Views import from `omero_plugin_common.request_utils` for JSON parsing and username resolution.

### OMERO connections
- Never use `BlitzGateway.suConn()` for user impersonation. The `job-service` account is intentionally non-admin, so `suConn` always returns `None`. Use the service connection directly with the correct group context (`SERVICE_OPTS.setOmeroGroup`) instead. The import CLI runs under the real user's session, so dataset ownership is resolved at import time.
- When the user's request connection (`conn`) is available, prefer it for dataset creation and OMERO API calls. Fall back to the service connection only when `conn` is `None` (background threads).

### Docker and infrastructure
- Pin all image tags in `docker-compose.yml` and Dockerfiles. Never use `:latest`.
- Do not add build `args:`, environment variables, or version pins to `docker-compose.yml`. Keep it minimal — configuration belongs in `env/*_example.env` files and Dockerfile `ARG` defaults.
- Every service must have a `healthcheck:` block and `security_opt: no-new-privileges:true`.
- Startup scripts must only consume environment variables; they must not import Python modules.
- The `omeroweb` container runs two processes via supervisord (OMERO.web + Celery worker).

### Security
- Keep secrets out of source control. The `env/` directory is gitignored except for `*_example.env` templates.
- Treat plugin input as untrusted; validate at system boundaries.
- Use OMERO permissions checks for data access.
- Do not expose monitoring interfaces without authentication.
- Interactive installation defaults Docker image security hardening to enabled, while Docker Scout vulnerability scanning remains opt-in.
- Locale data is preserved across the hardened images; package and dependency updates are the intended security control.

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

**Important:** Run each test directory as a **separate** `pytest` invocation. The root `conftest.py` installs mock stubs that interfere across test modules when run together in a single process. A combined `pytest tests/ omero_plugin_common/tests/ ...` call produces false failures.
In root-owned deployment clones, disable the pytest cache provider so the verification run stays warning-free when the repo root is not writable.

```bash
# Run docs structure validation (always run this)
python3 tools/lint_docs_structure.py

# Run docs lint tests
python3 -m unittest -v tests/test_lint_docs_structure.py

# Run all test suites (each separately, warning-free)
python3 -m pytest tests/ -v -p no:cacheprovider -W error
python3 -m pytest omero_plugin_common/tests/ -v -p no:cacheprovider -W error
python3 -m pytest omeroweb_imaris_connector/tests/ -v -p no:cacheprovider -W error
python3 -m pytest omeroweb_admin_tools/tests/ -v -p no:cacheprovider -W error
python3 -m pytest omeroweb_omp_plugin/tests/ -v -p no:cacheprovider -W error
python3 -m pytest omeroweb_import/tests/ -v -p no:cacheprovider -W error
```

## Build and deploy

```bash
# Build all images
docker compose --env-file installation_paths.env --env-file env/omero_secrets.env build

# Start all services
docker compose --env-file installation_paths.env --env-file env/omero_secrets.env up -d

# Check service health (requires secrets env files to be provisioned)
docker compose --env-file installation_paths.env --env-file env/omero_secrets.env ps
# Fallback if secrets env files are missing:
docker ps --format "table {{.Names}}\t{{.Status}}"

# View logs for a service
docker compose --env-file installation_paths.env --env-file env/omero_secrets.env logs -f omeroweb
```

## Git operations

- Repository files are owned by `root`. You need `sudo chown -R <user>:<user> /opt/omero/.git` before any git write operation (fetch, checkout, push, stash).
- Do not chown bind-mounted data directories (`postgresdb/`, `omero_data/`, `omero_temp/`) — this breaks container permissions.
- Commits may exist in worktrees or standalone clones under `/tmp/omero-*`, not just in the main repo. Search there if `git cat-file -t <hash>` fails.
- Always force-update tracking refs before rebase: `git fetch origin <branch>:refs/remotes/origin/<branch> --force`
