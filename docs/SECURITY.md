# Security

Security practices and controls for this deployment.

## Secrets management

- Keep secrets out of source control. The `env/` directory is gitignored except for `*_example.env` templates.
- Treat `*_example*` files as the authoritative in-repo templates; corresponding non-example files are deployment-local runtime artifacts managed by the sysadmin.
- `env/omero_secrets.env` is operator-managed secret material. AI agents must never create, edit, overwrite, or delete it.
- `env/omeroserver.env`, `env/omeroweb.env`, `env/omero-celery.env`, and `env/grafana.env` contain credentials and must never be committed.
- `installation_paths.env` is also gitignored (contains site-specific paths).
- Rotate all default credentials from example env files before deployment. This includes: database passwords, OMERO root password, job-service account password, Grafana admin password, hash secrets (`FMP_HASH_SECRET`, `OMERO_FIGURE_HASH_SECRET`), and LDAP bind credentials/filter settings.
- The `github_pull_project_bash_example` update script preserves `env/` and `installation_paths.env`, keeps existing site-local `logo/logo.png` in place (while refreshing `logo/logo_example.png` from templates), and does not overwrite non-example runtime files during repository updates. The real `logo/logo.png` asset is deployment-local and gitignored.

## Container security

- All containers run with `security_opt: no-new-privileges:true`.
- The `omeroserver` container drops to the `omero-server` user at runtime (non-root).
- The `omero-celery-worker` container runs as a dedicated `celery` user (uid/gid 10001).
- Redis runs with `maxmemory 512mb` and `allkeys-lru` eviction on tmpfs (no persistent state).
- `cadvisor` runs privileged because it inspects host/container runtime state for metrics.
- The `redis-sysctl-init` image defaults to a named non-root user, but the
  profile-gated (`sysctl-init`) Compose sidecar runs as `root` with
  `privileged: true` because applying `vm.overcommit_memory=1` is a host kernel
  sysctl write. It is only needed for non-standard deployments; the installation
  script persists the sysctl on the host.

## Post-build vulnerability scanning

Vulnerability scanning is **disabled by default** and can be enabled during
installation by answering "yes" to the interactive prompt or by setting
`ENABLE_VULNERABILITY_SCAN=1`. When enabled, the installation script runs
[Docker Scout](https://docs.docker.com/scout/) to report known CVEs in all
images referenced by `docker-compose.yml` — both custom-built images
(omero-server, omero-web, crowdsec, pg-maintenance, path-usage-exporter,
redis-sysctl-init) and third-party images (Prometheus, Grafana, Loki, Redis,
PostgreSQL, etc.).

The scan operates in two phases:

1. **Pre-build baseline** (cache-disabled builds only): Pulls upstream base images from each Dockerfile's `FROM` line, scans them, and stores the results. Images pulled solely for baseline scanning that are not needed at runtime are automatically removed after the report.
2. **Post-build report**: Scans every image from `docker-compose.yml` and displays a compact table. Third-party images not yet local are pulled for scanning and retained (they will be used when containers start). When baseline data is available, the table shows Before (upstream) and After (built) columns for side-by-side comparison.

Docker Scout is optional — if the CLI plugin is not installed, both phases are silently skipped and installation proceeds normally. The scan never blocks the installation.

## Security hardening (optional)

Interactive installation defaults Docker image security hardening to **yes**. Set `APPLY_SECURITY_HARDENING=0` or answer "no" to skip it. Setting `APPLY_SECURITY_HARDENING=1` also enables the same build pass explicitly:

1. **OS packages**: Runs `dnf update` (Rocky-based images) or `apt-get upgrade` (Ubuntu-based) or `apk upgrade` (Alpine-based) to patch known vulnerabilities in system libraries.
2. **Python packages**: Applies curated compatibility-safe Python updates only. The hardening pass does **not** blanket-upgrade entire OMERO/plugin virtual environments after OMERO/plugin packages are installed.
3. **Targeted fixes**: Upgrades specific high-value packages (`cryptography`, `urllib3`, `certifi`, `jinja2`, `pyopenssl`) even without the broad hardening flag.

Locale data is intentionally preserved across the hardened images for compatibility and multilingual support; the hardening pass focuses on package and dependency updates rather than locale stripping. Blanket post-install venv upgrades are intentionally avoided because they can override pinned/plugin-dependent stacks such as `omero-web-zarr` and its Zarr compatibility constraint.

## Image pinning

- All Docker images in `docker-compose.yml` use explicit version tags (e.g., `postgres:16.12`, `redis:8.6.2-alpine`).
- Dockerfiles pin base images and key package versions (e.g., `omero-py==5.22.0`, `celery==5.3.6`).
- Dependabot monitors pip and Docker dependencies weekly and opens PRs for updates.

## Input validation

- Treat all plugin input as untrusted. Validate at system boundaries (HTTP request handlers).
- Plugin views use `omero_plugin_common.request_utils.parse_json_body()` for safe JSON parsing.
- OMERO permissions are checked for every data access operation (project, dataset, image).
- The OMP plugin validates regex patterns before applying them to filenames.
- The Import plugin sanitizes filenames and validates file paths before import.
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
