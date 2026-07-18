# Deployment Quick Start

## Prerequisites

- docker engine and docker compose plugin installed.
- Host storage paths prepared for OMERO data and logs.
- Appropriate filesystem permissions for container users.

## 1) Configure Environment Files

Create deployment-local runtime files from the tracked templates, then review and update:

- `installation_paths_example.env` -> `installation_paths.env`
- `.env_example` -> generated `.env` defaults for Compose-only interpolation
- `env/omeroserver_example.env` -> `env/omeroserver.env`
- `env/omeroweb_example.env` -> `env/omeroweb.env`
- `env/omero-celery_example.env` -> `env/omero-celery.env`
- `env/grafana_example.env` -> `env/grafana.env`
- `env/omero_secrets_example.env` -> `env/omero_secrets.env` (ALL credentials live here; keep runtime secret files only on the server)

Do not deploy with default credentials.

After `installation/installation_script.sh` runs, generated `.env` mirrors the
variables Compose needs before service-level `env_file:` loading, including the
project name, bind paths, required ports/settings, and build version pins. Plain
`docker compose <command>` then works from the installation root.

Before any manual compose command, run:

```bash
python3 tools/env_safety_guard.py check
python3 tools/env_safety_guard.py compose-guard
```

IMPORTANT: Runtime env files contain deployment-local values. Do not rewrite
non-example env files unless the operator explicitly grants that one-off action.
After installation, generated `.env` includes
`COMPOSE_ENV_FILES=installation_paths.env,env/omero_secrets.env,env/omeroserver.env,env/omeroweb.env,env/omero-celery.env,env/grafana.env`
for shells/tools that honor it, but agent and script runbooks should still pass
explicit `--env-file` arguments for portability.

If `.env` is missing before first installation, export required values first:

```bash
set -a
source .env_example
source installation_paths.env
source env/omeroserver.env
source env/omeroweb.env
source env/omero-celery.env
source env/grafana.env
source env/omero_secrets.env
set +a
```

From an installed root with `.env`, pass the full explicit env-file list when a
script or agent must be first-attempt portable:

```bash
docker compose --env-file .env --env-file installation_paths.env --env-file env/omero_secrets.env --env-file env/omeroserver.env --env-file env/omeroweb.env --env-file env/omero-celery.env --env-file env/grafana.env <command>
```

If `.env` is missing, omit only `--env-file .env` from that command.

## 2) Easy Installation From a Prebuilt Carrier Image

The easy installation path consumes a single manually released docker hub
carrier image instead of building dockerfiles on the installation host. The
carrier image tag and GitHub release tag are the same docker-compatible SemVer
string, for example `1.0.0-main.1`.

From an installation root that already has reviewed runtime env files:

```bash
bash installation/easy_installation_script.sh
```

The first easy-installer prompts ask which prebuilt docker image tag to install
and which immutable carrier digest from the GitHub release asset
`prebuilt-carrier-digest.txt` must be verified. Enter the docker hub carrier
image tag, for example `1.0.0-main.1`, and the matching
`PREBUILT_IMAGE_DIGEST` value. `installation/easy_installation_script.sh` then
delegates to the canonical installer with `PREBUILT_IMAGE_MODE=require`. It
removes the local build-only questions from the interactive flow:

- `Enable Buildx compressed build workflow?`
- `Use build cache?`
- `Flatten final images into single-layer outputs?`
- `Enable docker image security hardening?`

The three release-build settings are enforced by the manual release workflow
before publishing the carrier; the build-cache setting has no local build to
control in strict prebuilt mode. The easy installer asks eleven questions
total, including the docker-image-tag and digest prompts, and still uses the same host
paths, runtime env files, UID/GID discovery, permission checks, data-path
snapshots, container startup, and post-start validation flow as the standard
installer. If the carrier cannot be pulled, verified, extracted, or loaded, the
easy installation exits with an error and does not run `docker compose build`.

The carrier stores a manifest and a compressed docker image archive. The loader
requires a digest-pinned carrier image reference, verifies Docker pulled the
expected `sha256:` carrier digest, then verifies the manifest schema, release
value, runtime-image references, archive size, uncompressed docker-save size,
and archive SHA-256 before `docker load`.
It streams the verified archive from the carrier image into docker instead of
writing an extra full archive copy under `OMERO_TMP_PATH`, checks free space
under docker's root directory, then verifies each required image tag exists in
the local docker daemon. The final Compose startup uses `--no-build`.

Flattening in the release workflow applies to the bundled runtime service
images inside `runtime-images.tar.gz`. The docker hub carrier is a scratch-based
data image with one payload layer for the manifest, required-image list, and
archive; it has no Alpine, BusyBox, package manager, or shell layer and uses
`HEALTHCHECK NONE` metadata instead of a runnable healthcheck command.

For unattended runs, set both `PREBUILT_IMAGE_RELEASE` and
`PREBUILT_IMAGE_DIGEST` explicitly:

```bash
PREBUILT_IMAGE_RELEASE=1.0.0-main.1 \
PREBUILT_IMAGE_DIGEST=sha256:<64 lowercase hex characters> \
bash installation/easy_installation_script.sh
```

Carrier releases are created from the GitHub Actions panel with the manual
`release-prebuilt-carrier` workflow. Configure `DOCKERHUB_USERNAME` and
`DOCKERHUB_TOKEN` as repository secrets before dispatching that workflow. The
workflow uses the built-in `GITHUB_TOKEN` with job-scoped `contents: write`
permission to create the GitHub release; no separate GitHub PAT secret is
required when repository Actions settings allow workflow write permissions. The
release targets the default branch ref, creates a draft GitHub release with
source artifacts, enables and verifies Docker Scout repository analysis for the
Docker Hub repository, pushes and verifies the carrier image, uploads
`prebuilt-carrier-digest.txt`, runs Docker Scout `quickview`, `cves`, and
`sbom` against the pushed Docker Hub tag, then publishes the release. The
carrier push includes BuildKit SBOM and provenance attestations so Docker Hub
and Docker Scout have metadata for automatic image analysis. If Docker Scout
repository enablement, the carrier publish, or Scout analysis fails after the
draft was created, the workflow deletes that draft release and its tag. The
release job deliberately does not use a GitHub Actions environment,
because job environments create deployment records. Keep the Docker Hub
credentials as repository secrets with the documented names. To rebuild an
existing release without changing its version, dispatch the workflow with an
explicit `release_version` and `replace_existing=true`; replacement mode first
verifies that at least one release artifact exists, builds the replacement,
then deletes and verifies the absence of the prior GitHub release/tag and Docker
Hub image tag before creating new artifacts with the requested version. A
partially deleted prior release can therefore be recovered by rerunning the same
replacement dispatch. Before
saving the runtime archive, the workflow derives the required image references
from Compose and prunes only
runner-local docker images outside that required set, reducing hosted-runner
storage pressure without changing the carrier contents. On GitHub-hosted Linux
runners it also moves Docker's data root to `/mnt/docker-data` before the heavy
build and archive steps so the full required image set fits on the runner. The
`DOCKERHUB_TOKEN`
value must be a docker hub access token with write access to the carrier
repository; do not use a docker hub account password.

## 3) Build Images

```bash
docker compose --env-file .env --env-file installation_paths.env --env-file env/omero_secrets.env --env-file env/omeroserver.env --env-file env/omeroweb.env --env-file env/omero-celery.env --env-file env/grafana.env build
```

### Optional: Build + push compressed images with Buildx

For registry-oriented deployments, use BuildKit/Buildx compression to reduce
image transfer size and improve pull speed. The repository includes an example
helper script that wraps `docker buildx bake` and validates required inputs:

```bash
DOCKER_REGISTRY_PREFIX=myregistry.example.com/omero \
DOCKER_IMAGE_TAG=2026.02.0 \
DOCKER_BUILD_COMPRESSION_TYPE=zstd \
DOCKER_BUILD_COMPRESSION_LEVEL=15 \
./installation/docker_buildx_compressed_push.sh
```

Notes:

- If unset, `DOCKER_IMAGE_TAG` defaults to `custom`.
- Compression is explicit and environment-driven (`DOCKER_BUILD_COMPRESSION_*`).
- When push mode is disabled (`DOCKER_BUILD_PUSH_IMAGES=0`, the default without `DOCKER_REGISTRY_PREFIX`), the helper builds local images without `force-compression=true` to avoid unnecessary BuildKit recompression/memory pressure.
- When `DOCKER_REGISTRY_PREFIX` is set, `DOCKER_BUILD_PUSH_IMAGES` defaults to `1` (push enabled).
- When `DOCKER_REGISTRY_PREFIX` is unset, `DOCKER_BUILD_PUSH_IMAGES` defaults to `0` (local images only).
- By default, build targets are auto-discovered from the active rendered `docker compose config` output (services with a `build:` block in the currently enabled profile set).
- Override `DOCKER_BUILD_TARGETS` only if you explicitly want a subset of services.
- `DOCKER_REGISTRY_PREFIX` is only required when push mode is enabled.
- `DOCKER_BUILD_PROGRESS` defaults to `plain` for both `docker compose build`
  and Buildx helper paths. This keeps installer transcripts line-oriented and
  stable when terminals are resized. Set it to another docker-supported
  progress mode only when you explicitly need interactive TTY progress.
- Transient Buildx export failures are retried automatically, including layer-lock contention (`(*service).Write failed ... ref layer-sha256:... locked ... unavailable`) and cache-export transport failures (`failed to receive status ... Unavailable ... EOF`).
- OMERO.web and OMERO.server image builds now harden Rocky package retrieval by
  default: retry transient `dnf` metadata/package fetch failures (for example
  mirror `500/504` responses), try Rocky `mirrorlist` only
  after the first `dnf` failure, then clean metadata/cache before retrying so
  transient mirror errors can recover without changing first-attempt behavior.
  The default profile is intentionally strict: 3 attempts, no inter-attempt
  sleep, `--setopt=timeout=20`, and `--setopt=retries=2`.
- Advanced override: docker builds can tune these safeguards with `--build-arg DNF_MAX_ATTEMPTS=...`, `--build-arg DNF_RETRY_SLEEP_SECONDS=...`, and `--build-arg DNF_USE_ROCKY_MIRRORLIST=0|1`.
- During `pg-maintenance` image builds on Debian-based images, `invoke-rc.d`/`policy-rc.d` and `sysctl: permission denied on key ...` messages can appear while package post-install scripts run in an unprivileged build container; these are expected build-time warnings when the layer still completes successfully.
- Retry behavior is configurable via `DOCKER_BUILD_BAKE_RETRY_COUNT` (default: `3`) and `DOCKER_BUILD_BAKE_RETRY_SLEEP_SECONDS` (default: `2`).
- `DOCKER_BUILD_BAKE_SERIAL_MODE` controls execution strategy: `auto` (default), `always`, or `never`.
- `DOCKER_BUILD_PROVENANCE` defaults to `0`, so compose, Buildx, and flatten-rebuild steps all pass `--provenance=false` by default. Set `DOCKER_BUILD_PROVENANCE=1` only if you explicitly need BuildKit provenance attestations and accept the extra metadata export time.
- `DOCKER_BUILD_FLATTEN_FINAL_IMAGE` now defaults to `0`, so flattening is
  opt-in for both build workflows. When enabled, Buildx builds flatten their
  temporary source images after `buildx bake`; plain `docker compose build`
  runs the same flatten helper immediately afterward against the compose-built
  local images. In both cases, each target is rebuilt from `scratch` with a
  single filesystem `COPY --from=source / /`, then metadata is restored
  (`ENV`, `ENTRYPOINT`, `CMD`, `EXPOSE`, `VOLUME`, `WORKDIR`, `USER`,
  `STOPSIGNAL`, `HEALTHCHECK`, `LABEL`, `ONBUILD`) via
  `docker image import --change ...`. This produces a true single-layer final
  image for the local docker daemon, but it is intentionally slower because
  every selected image is exported and re-imported. Set
  `DOCKER_BUILD_FLATTEN_FINAL_IMAGE=1` to enable it. Temporary source
  tags/build contexts are cleaned automatically, and flatten metadata
  generation now fails fast if source-image inspection or metadata restoration
  cannot be completed.
- The helper enforces `DOCKER_BUILDX_DRIVER=docker-container` and will fail fast if another driver is requested (local cache export requires the containerized BuildKit driver).
- Optional `DOCKER_BUILDX_DRIVER_OPTS` (comma-separated `key=value` values) are passed through to `docker buildx create --driver-opt` for deterministic BuildKit sizing/tuning.
- Set `DOCKER_BUILDX_FORCE_RECREATE_BUILDER=1` to force builder recreation when testing driver/driver-opt changes.
- `DOCKER_BUILDX_KEEP_BUILDER` defaults to `0`, so the installation/build helper removes the temporary Buildx builder, any BuildKit containers, and builder-owned volumes after a Buildx run. Set `DOCKER_BUILDX_KEEP_BUILDER=1` only if you explicitly want to preserve that state between runs.
- In `auto` mode, multi-target cached builds run serially up front when local cache export is enabled (to avoid known BuildKit local-cache lock contention); if lock contention still appears in parallel mode, the helper switches to serial per-target `buildx bake` execution.
- Root cause note: observed hangs occur during BuildKit local cache export (`exporting cache to client directory`) and are amplified by `cache-to mode=max` on large multi-stage images.
- Local cache export remains enabled by default (`DOCKER_BUILD_LOCAL_CACHE_ENABLED=1`), but now uses `DOCKER_BUILD_LOCAL_CACHE_MODE=min` by default to reduce cache-export pressure while keeping deterministic cache reuse.
- Local cache export now writes each target into a per-run staging directory and atomically swaps it into place only after a successful build, preventing unbounded stale cache growth from interrupted/failed exports.
- Set `DOCKER_BUILD_LOCAL_CACHE_MODE=max` only when you explicitly need full cache graph export despite the higher risk of long export phases.
- If retries still fail with cache-export transport errors, the helper automatically performs one final build with local cache export disabled for that run (compression remains enabled).
- Image compression settings (`DOCKER_BUILD_COMPRESSION_TYPE`, `DOCKER_BUILD_COMPRESSION_LEVEL`, `force-compression=true`) are unchanged by local cache mode; compressed image output remains enabled.
- When `DOCKER_BUILD_FLATTEN_FINAL_IMAGE=1` and `DOCKER_BUILD_PUSH_IMAGES=1`, the helper pushes the flattened final images via `docker push` after the flatten step. This preserves the single-layer result, but Buildx-specific output compression settings do not apply to that final publish step.
- The installation workflow prompts whether to enable the compressed Buildx mode during each interactive run (default: `No`). If you disable it, the script uses `docker compose build`.
- Immediately after the `Use build cache?` prompt, the installation workflow asks whether to flatten final images into single-layer outputs (default: `No`). In unattended automation, the same default applies unless you explicitly set `DOCKER_BUILD_FLATTEN_FINAL_IMAGE=1`. Run:
- If you answer **No** to the installation prompt `Use build cache?`, the installer later prints a cache-cleanup notice just before the rebuild starts and performs deterministic local cache cleanup:
  - always prunes docker builder cache (`docker builder prune -a -f`),
  - when Buildx compressed workflow is enabled for that run, also removes the Buildx local cache directory (auto-detected from `BUILDX_DATA_PATH` or defaulting to `${OMERO_DATA_PATH}/buildx_cache`),
  - and, for that Buildx run, forces Buildx local cache export off in addition to disabling docker layer cache and Buildx inline cache.
  This keeps "no cache" runs consistent with operator expectations while avoiding unnecessary Buildx cache deletion when Buildx is disabled.

```bash
bash installation/installation_script.sh
```

- To push compressed images to a registry, run:

```bash
DOCKER_REGISTRY_PREFIX=myregistry.example.com/omero \
DOCKER_IMAGE_TAG=2026.02.0 \
bash installation/installation_script.sh
```

- `installation/github_pull_project_bash` preserves the installation script prompts by default.
- `installation/github_pull_project_bash` uses `REPO_BRANCH` when set and otherwise resolves the repository's remote default branch.
- The first standard pull/update prompt selects the source version. Empty input
  or `latest` installs the latest commit from that resolved branch; an exact
  GitHub release tag installs that release's source tree; a commit hash installs
  that commit. Invalid or unavailable selections fail before repository files
  are replaced.
- For unattended source selection, set `REPO_SOURCE_REF` to `latest`, the
  release tag, or the commit hash. If `REPO_SOURCE_REF` is unset while
  `INSTALLATION_AUTOMATION_MODE=1`, the launcher uses `latest`.
- For unattended automation, you can explicitly set `INSTALLATION_AUTOMATION_MODE=1`.
- `installation/installation_script.sh` rewrites `installation_paths.env` only after path prompts are resolved (installation path, database path, plugin database path, data path, and tmp path), so selected non-default paths are persisted immediately for future pull/update runs.
- `installation/github_pull_project_bash` saves the visible terminal session to `${OMERO_DATA_PATH}/installation_logs/<script>_<UTC timestamp>.log` after the run finishes.

- To integrate with the pull/update workflow, run:

```bash
bash installation/github_pull_project_bash
```

### Post-build vulnerability report

Vulnerability scanning is disabled by default (it adds several minutes). To
enable it, answer "yes" to the interactive prompt or set
`ENABLE_VULNERABILITY_SCAN=1`. When enabled, docker scout reports known CVEs in
all images referenced by `docker-compose.yml`, both custom-built and
third-party. When the build ran without cache (fresh pull), the report includes
a before/after baseline comparison. The output is a compact table with one line
per image.

Interactive installation defaults security hardening to `yes`, and the hardening pass keeps locale data intact while still applying OS updates plus curated compatibility-safe Python updates. It does not blanket-upgrade OMERO/plugin virtual environments after OMERO/plugin packages are installed. To force hardening explicitly in automation, use:

```bash
APPLY_SECURITY_HARDENING=1 bash installation/installation_script.sh
```

If you also want the optional CVE report, add `ENABLE_VULNERABILITY_SCAN=1`. See `docs/SECURITY.md` for details.

## 4) Start the Platform

```bash
docker compose --env-file .env --env-file installation_paths.env --env-file env/omero_secrets.env --env-file env/omeroserver.env --env-file env/omeroweb.env --env-file env/omero-celery.env --env-file env/grafana.env up -d
```

## 5) Verify Service Health

```bash
docker compose --env-file .env --env-file installation_paths.env --env-file env/omero_secrets.env --env-file env/omeroserver.env --env-file env/omeroweb.env --env-file env/omero-celery.env --env-file env/grafana.env ps
```

Verify all required services are `healthy` or `running`.

## 6) Basic Connectivity Checks

```bash
container="$(docker compose --env-file .env --env-file installation_paths.env --env-file env/omero_secrets.env --env-file env/omeroserver.env --env-file env/omeroweb.env --env-file env/omero-celery.env --env-file env/grafana.env ps -q omeroweb)"
base_url=""
while read -r _arrow_prefix _arrow binding; do
  [ -n "${binding:-}" ] || continue
  host="${binding%:*}"
  port="${binding##*:}"
  host="${host#[}"
  host="${host%]}"
  case "$host" in
    ""|0.0.0.0|::) host="127.0.0.1" ;;
    *:*) host="[${host}]" ;;
  esac
  candidate="http://${host}:${port}"
  if curl -fsS -o /dev/null "${candidate}/webgateway/"; then
    base_url="$candidate"
    break
  fi
done < <(docker port "$container")
[ -n "$base_url" ] || { echo "OMERO.web binding not found" >&2; exit 1; }
curl -I "$base_url"
```

This discovers the active host binding by probing the running container's
published ports; do not assume the shipped default port if Compose or env values
were changed.

## 6) First Operational Checks

- Confirm OMERO.server and OMERO.web logs show successful startup.
- Confirm plugin menu entries are visible in OMERO.web.
- Confirm Celery worker process is active if Imaris export is enabled.
- Confirm monitoring endpoints are scraping targets.

## Lifecycle Commands

```bash
# Stop services without removing resources
docker compose --env-file .env --env-file installation_paths.env --env-file env/omero_secrets.env --env-file env/omeroserver.env --env-file env/omeroweb.env --env-file env/omero-celery.env --env-file env/grafana.env stop

# Stop and remove containers
docker compose --env-file .env --env-file installation_paths.env --env-file env/omero_secrets.env --env-file env/omeroserver.env --env-file env/omeroweb.env --env-file env/omero-celery.env --env-file env/grafana.env down

# Follow logs for a service
docker compose --env-file .env --env-file installation_paths.env --env-file env/omero_secrets.env --env-file env/omeroserver.env --env-file env/omeroweb.env --env-file env/omero-celery.env --env-file env/grafana.env logs -f omeroweb

# Remove optional post-build leftovers (redis-sysctl-init + buildx buildkit)
bash installation/cleanup_build_containers.sh
```

## External Reverse Proxy setup (IT-managed)

1. Configure your external reverse proxy (for example, nginx managed via Ansible) to forward traffic to `omeroweb` on `CONFIG_omero_web_application__server_port`.
2. Keep direct local HTTP access available on `OMERO_WEB_HOST_PORT` for troubleshooting when needed.
3. Manage TLS certificates in your external proxy stack.
