# Security

Security practices and controls for this deployment.

## Secrets management

- Keep secrets out of source control. The `env/` directory is gitignored except for `*_example.env` templates.
- Treat `*_example*` files as the authoritative in-repo templates; corresponding non-example files are deployment-local runtime artifacts managed by the sysadmin.
- `env/omero_secrets.env` is operator-managed secret material. AI Agents must never create, edit, overwrite, or delete it.
- `env/omeroserver.env`, `env/omeroweb.env`, `env/omero-celery.env`, and `env/grafana.env` contain credentials and must never be committed.
- `installation_paths.env` is also gitignored (contains site-specific paths).
- Provide deployment-local credentials before deployment. The tracked secret example keeps values empty; database passwords, OMERO root password, job-service account password, Grafana admin password, hash secrets (`OMP_HASH_SECRET`, `FMP_HASH_SECRET`), and LDAP bind credentials/filter settings must be set only in deployment-local env files.
- The `github_pull_project_bash_example` update script preserves `env/` and `installation_paths.env`, keeps existing site-local `logo/logo.png` in place (while refreshing `logo/logo_example.png` from templates), and does not overwrite non-example runtime files during repository updates. The real `logo/logo.png` asset is deployment-local and gitignored.

## Container security

- All containers run with `security_opt: no-new-privileges:true`.
- The `omeroserver` and `omeroweb` images default to their application users
  (`omero-server` and `omero-web`). Compose runs those services as `root` only
  for startup bind-mount reconciliation, and the entrypoints drop to the
  application users before launching the long-running processes.
- The `omero-celery-worker` container runs as a dedicated `celery` user (uid/gid 10001).
- Redis runs without persistent state. Compose requires the generated `.env`
  file to provide `REDIS_MAXMEMORY`, `REDIS_MAXMEMORY_POLICY`,
  `REDIS_DATA_TMPFS_SIZE`, `REDIS_APPENDONLY`, and `REDIS_SAVE_POLICY`;
  missing Redis env keys fail Compose interpolation instead of using a hidden
  Compose-side default.
- `cadvisor` runs privileged because it inspects host/container runtime state for metrics.
- The `crowdsec`, `pg-maintenance`, and `redis-sysctl-init` helper images
  default to non-root users. Compose explicitly runs these helper services as
  `root` only where the runtime boundary requires it: CrowdSec manipulates the
  host firewall with `NET_ADMIN`, pg-maintenance starts system cron and writes
  a private `0600` shell-quoted cron environment under `/etc`, and
  redis-sysctl-init applies the host-kernel `vm.overcommit_memory=1` sysctl
  with `privileged: true`.

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

The prebuilt carrier release workflow always builds the bundled custom runtime
images with `APPLY_SECURITY_HARDENING=1` and
`DOCKER_BUILD_FLATTEN_FINAL_IMAGE=1` before publishing the carrier. The easy
installation path therefore skips the local hardening prompt and loads only the
release-built images from the verified carrier bundle.

## Image pinning

- All Docker images in `docker-compose.yml` use explicit version tags (e.g.,
  `postgres:16.12`, `redis:8.6.3-alpine`). Untagged images and floating aliases
  such as `latest`, `stable`, `edge`, `main`, `master`, `nightly`, `rolling`, or
  `current` are prohibited.
- Dockerfiles pin base images and key package versions (e.g., `omero-py==5.22.1`, `celery==5.6.3`).
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

- By default, only `omeroserver` (`OMERO_SERVER_HOST_PORT`, default 4064), `omeroweb` (`OMERO_WEB_HOST_PORT`, default 4090), `portainer` (9000/9443), `prometheus` (9090), `grafana` (3000), and `loki` (3100) are exposed to the host.
- When the `crowdsec` profile is enabled, CrowdSec uses host networking and exposes its LAPI on host port 8080.
- All other services (databases, Redis, Ollama, exporters, alloy, blackbox, cadvisor, node-exporter) are internal to the `omero` Docker network.
- Restrict public access to monitoring interfaces (Grafana, Prometheus, Portainer) using firewall rules or a reverse proxy with authentication.
- OMERO.web should be behind a TLS-terminating reverse proxy for production use.
- Docker socket is mounted read-only in `omeroweb` for container stats (admin tools plugin).

## CSRF protection

OMERO.web CSRF trusted origins are configured via `CONFIG_omero_web_csrf__trusted__origins` in `env/omeroweb.env`. Update this list to match your deployment's domain(s).
