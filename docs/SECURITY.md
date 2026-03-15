# Security

Security practices and controls for this deployment.

## Secrets management

- Keep secrets out of source control. The `env/` directory is gitignored except for `*_example.env` templates.
- Treat `*_example*` files as the authoritative in-repo templates; corresponding non-example files are deployment-local runtime artifacts managed by the sysadmin.
- `env/omeroserver.env`, `env/omeroweb.env`, `env/omero-celery.env`, and `env/grafana.env` contain credentials and must never be committed.
- `installation_paths.env` is also gitignored (contains site-specific paths).
- Rotate all default credentials from example env files before deployment. This includes: database passwords, OMERO root password, job-service account password, Grafana admin password, hash secrets (`FMP_HASH_SECRET`, `OMERO_FIGURE_HASH_SECRET`), and LDAP bind credentials/filter settings.
- The `github_pull_project_bash_example` update script preserves `env/` and `installation_paths.env`, keeps existing site-local `logo/logo.png` in place (while refreshing `logo/logo_example.png` from templates), and does not overwrite non-example runtime files during repository updates.

## Container security

- All containers run with `security_opt: no-new-privileges:true`.
- The `omeroserver` container drops to the `omero-server` user at runtime (non-root).
- The `omero-celery-worker` container runs as a dedicated `celery` user (uid/gid 10001).
- Redis runs with `maxmemory 512mb` and `allkeys-lru` eviction on tmpfs (no persistent state).
- The `redis-sysctl-init` sidecar is the only privileged container, and it runs once and exits.

## Post-build vulnerability scanning

The installation script runs [Docker Scout](https://docs.docker.com/scout/) after every successful image build to report known CVEs in the final images. When the upstream base images are available locally (always the case for cache-disabled builds), the report includes a baseline comparison showing vulnerability counts for the unmodified upstream image alongside the built image.

Docker Scout is optional — if the CLI plugin is not installed, the scan is silently skipped and installation proceeds normally.

## Security hardening (optional)

Setting `APPLY_SECURITY_HARDENING=1` (or answering "yes" to the interactive prompt during installation) enables an additional build pass that:

1. **OS packages**: Runs `dnf update` (Rocky-based images) or `apt-get upgrade` (Ubuntu-based) or `apk upgrade` (Alpine-based) to patch known vulnerabilities in system libraries.
2. **Python packages**: Upgrades all outdated packages in each image's virtual environment, excluding pinned compatibility-critical packages (`omero-py`, `zeroc-ice`, `django`, `omero-web`).
3. **Targeted fixes**: Upgrades specific high-value packages (`cryptography`, `urllib3`, `certifi`, `jinja2`, `pyopenssl`) even without the broad hardening flag.

Upgrading transitive dependencies may affect OMERO compatibility in rare cases. Disable and rebuild if issues occur.

## Image pinning

- All Docker images in `docker-compose.yml` use explicit version tags (e.g., `postgres:16.12`, `redis:8.4.0-alpine`).
- Dockerfiles pin base images and key package versions (e.g., `omero-py==5.22.0`, `celery==5.3.6`).
- Dependabot monitors pip and Docker dependencies weekly and opens PRs for updates.

## Input validation

- Treat all plugin input as untrusted. Validate at system boundaries (HTTP request handlers).
- Plugin views use `omero_plugin_common.request_utils.parse_json_body()` for safe JSON parsing.
- OMERO permissions are checked for every data access operation (project, dataset, image).
- The OMP plugin validates regex patterns before applying them to filenames.
- The Upload plugin sanitizes filenames and validates file paths before import.
- The Admin Tools plugin restricts access to root users via `_require_root_user()`.

## Annotation ownership

The OMP plugin uses HMAC-based hash tags (`omp_hash` key with `omphash_v1:` prefix) to track which annotations it created. The hash includes the plugin ID and image/annotation metadata. An optional secret (`FMP_HASH_SECRET` env var) makes hashes unforgeable. Delete operations only remove annotations that match the plugin's hash.

## Rate limiting

The OMP plugin enforces per-user rate limits on major actions (job starts, bulk deletes):
- 6 major actions per 60-second window per user.
- 60-second block period when exceeded.
- Parameters configured in `omeroweb_omp_plugin/constants.py`.

## Network exposure

- Only `omeroserver` (4064), `omeroweb` (4090), `portainer` (9000/9443), `prometheus` (9090), `grafana` (3000), and `loki` (3100) are exposed to the host.
- All other services (databases, Redis, exporters, alloy, blackbox, cadvisor, node-exporter) are internal to the `omero` Docker network.
- Restrict public access to monitoring interfaces (Grafana, Prometheus, Portainer) using firewall rules or a reverse proxy with authentication.
- OMERO.web should be behind a TLS-terminating reverse proxy for production use.
- Docker socket is mounted read-only in `omeroweb` for container stats (admin tools plugin).

## CSRF protection

OMERO.web CSRF trusted origins are configured via `CONFIG_omero_web_csrf__trusted__origins` in `env/omeroweb.env`. Update this list to match your deployment's domain(s).
