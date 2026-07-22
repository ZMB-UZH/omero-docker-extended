# AI Agent Runtime Playbook

Deep operational guidance for AI Agents. `AGENTS.md` should route here instead of duplicating these details.

## Git ownership and local clones

- Deployment clones are often root-owned. `git` write operations can fail until ownership is fixed.
- If a read-only `git` command reports dubious ownership, use `git -c safe.directory=<repo> ...` for inspection.
- Do not `chown` bind-mounted data directories such as `postgresdb/`, `omero_data/`, or `omero_temp/` to a non-service user.
- Worktrees and related clones can exist under `/tmp/omero-*`. Search them before declaring a commit missing.
- Develop, commit, push, and verify on the current remote default branch unless the user explicitly names another branch. Resolve it dynamically; never create feature branches, PR branches, temporary remote branches, or draft PRs just to run workflows or scanner checks.
- Before rebasing, refresh tracking refs explicitly with `git fetch origin <branch>:refs/remotes/origin/<branch> --force`.
- GitHub HTTPS Git operations require a PAT or credential manager, never an account password. A `Password for 'https://github.com'` prompt is asking for a token-class credential.
- For TTY pushes, resolve the default branch first, then use `python3 tools/git_push_with_pat.py origin "HEAD:${default_branch}"`; it resolves the remote before reading the token, serves the token only for `https://github.com` prompts, prompts without echo, disables stale GitHub credential helpers for that command, and keeps the token out of argv, remotes, logs, temp files, and long-lived git config.
- In non-TTY agent shells, provide the PAT only as a short-lived `GITHUB_TOKEN`
  environment variable for that helper invocation; never paste it into argv,
  remotes, logs, temp files, or long-lived Git config.
- If a stale `gh auth git-credential` helper intercepts GitHub HTTPS auth, inspect `git config --show-origin --get-all credential.https://github.com.helper` and `gh auth status`, then use the prompt helper above or repair the credential manager before retrying.

## Cross-repository sync safety

- Treat repo-to-repo copying as tree-content sync, not branch-history integration.
- Resolve the remote default branch explicitly before pushing; do not assume it matches the local branch name.
- If there is no expected merge base, stop and follow `docs/operations/repository-sync-safety.md`.
- Keep dated `backup/<date>-<reason>/...` refs until the repaired branch family is verified.

## Docker compose and env files

- In this repo, agent/script `docker compose build`, `up`, `config`, `ps`, `logs`, and `exec` commands should use the full explicit env-file list from the installed root:
  `--env-file .env --env-file installation_paths.env --env-file env/omero_secrets.env --env-file env/omeroserver.env --env-file env/omeroweb.env --env-file env/omero-celery.env --env-file env/grafana.env`.
  If `.env` is missing, omit only `--env-file .env`.
- `COMPOSE_ENV_FILES` is comma-separated when exported in the shell, but do not rely on a value inside `.env` to activate additional env files for first-attempt agent commands. Use explicit `--env-file` arguments.
- `docker compose --env-file installation_paths.env ps` fails when the required secrets/server/web/Celery/Grafana env files are absent. Use `docker ps --format "table {{.Names}}\t{{.Status}}"` as the fallback probe.
- Before any `docker compose` command, run `python3 tools/env_safety_guard.py check` and `python3 tools/env_safety_guard.py compose-guard`. The compose guard refuses non-canonical worktrees and `.env` files whose `COMPOSE_PROJECT_NAME` does not match the installation path, preventing a second Compose project from attaching to the same live bind mounts.
- AI Agents may inspect non-example deployment env files and run `python3 tools/env_safety_guard.py template-check`, but must not create, edit, overwrite, delete, normalize, or print values from non-example env files unless the user explicitly grants a one-off exception for that exact operation.
- Functional OMERO, installation, Compose, startup, plugin-behavior, and env-contract changes require fresh-code live verification before commit/push when live testing makes sense or the user explicitly requests it: reconcile the canonical live root to the exact checkout under test, then rebuild, inject, or restart affected services so containers cannot run stale code.
- A stale or dirty canonical live root is cleanup work, not a reason to skip live verification. Inspect `git status` before rebuilds; preserve unrelated dirty work non-destructively with a commit, stash, patch, or user-approved cleanup; then update the live root, rerun env guards, rebuild/restart, and test. Stop only when safe reconciliation is impossible.
- Treat env files and Compose as mutable administrator-owned contracts. Product
  code, tests, tools, and live probes must read configured values or discover
  active runtime state instead of assuming default host ports, container names,
  absolute paths, service users, or enabled profiles.
- Treat Docker socket access as optional. A permission error matters only when
  Docker-backed diagnostics were explicitly enabled; it is not proof that
  Docker or OMERO is down.
- Treat plugin tmp helpers as non-mutating path resolvers unless the immediate runtime sink truly needs the directory to exist. Import-time or root-context helper calls that eagerly create `OMERO_TMP_PATH` plugin subtrees can leave `omeroweb-*` paths owned by the wrong UID and break later non-root request handling.

## OMERO.web env variable naming convention (CRITICAL)

OMERO.web configuration properties are set via `CONFIG_omero_web_*` environment variables in `env/omeroweb.env`. The translation from OMERO config property names to Docker env variable names follows strict rules:

- **Dots (`.`) become single underscores (`_`)**: `omero.web.session_engine` → `CONFIG_omero_web_session_engine`
- **Underscores (`_`) become DOUBLE underscores (`__`)**: `omero.web.session_cookie_age` → `CONFIG_omero_web_session__cookie__age`

Examples:

| OMERO config property                          | Docker env variable                                      |
| ---------------------------------------------- | -------------------------------------------------------- |
| `omero.web.session_engine`                     | `CONFIG_omero_web_session__engine`                       |
| `omero.web.session_cookie_age`                 | `CONFIG_omero_web_session__cookie__age`                  |
| `omero.web.session_expire_at_browser_close`    | `CONFIG_omero_web_session__expire__at__browser__close`   |
| `omero.web.csrf_trusted_origins`               | `CONFIG_omero_web_csrf__trusted__origins`                |
| `omero.web.application_server_port`            | `CONFIG_omero_web_application__server__port`             |

**Common mistake**: using single underscores where doubles are required. `CONFIG_omero_web_session_engine` (wrong) vs `CONFIG_omero_web_session__engine` (correct). The single-underscore version silently creates a different (nonexistent) config property.

## Docker image rebuilds: cached vs no-cache

- `docker compose build <service>` uses the layer cache. This is fast but will NOT pick up changes to build ARGs that are already baked into a cached layer. Use this for code-only changes (Python files, templates, static assets) where the COPY layers invalidate naturally.
- `docker compose build --no-cache <service>` rebuilds every layer from scratch. Use this when changing build ARGs (package versions like `BIOFORMATS2RAW_VERSION`, `OME_ZARR_PY_VERSION`), base image digests, or OS-level package lists.
- If a live installation build starts transferring GBs of context, stop before
  `up` and inspect `.dockerignore`; generated runtime roots such as
  `omero_data/`, `omero_temp/`, `postgresdb/`, `node_modules/`, and
  `.project-pull.*/` must stay excluded from build contexts.
- Build ARGs such as `OMERO_DROPBOX_VERSION`, `BIOFORMATS2RAW_VERSION`, and
  `BIOFORMATS_SHA256` come from `env/omeroserver.env`. `docker-compose.yml`
  and `docker/<service>.Dockerfile` fail closed when those values are absent
  instead of silently falling back to in-code defaults.

## Prebuilt carrier and easy installation

- The standard installer and `installation/easy_installation_script.sh` must
  stay interchangeable. Both paths use the same deployment-local env files,
  installation paths, UID/GID discovery, permission checks, data-path snapshots,
  Compose startup, and post-start validation; only the image acquisition path
  differs.
- The easy installer must require `PREBUILT_IMAGE_MODE=require` and fail if the
  release carrier cannot be pulled, verified, streamed, or loaded. Do not add a
  branch that switches from easy installation back to a local image build.
- `docker/prebuilt-carrier.Dockerfile` is intentionally `FROM scratch`: it is a
  data carrier for the manifest, required-image list, and
  `runtime-images.tar.gz`. Do not add Alpine, BusyBox, a shell, a package
  manager, a healthcheck command, or a later ownership/mode mutation layer.
- The manual `release-prebuilt-carrier` workflow is the only manual release
  workflow. It builds hardened flattened runtime service images, writes the
  source archive and manifest, pushes one attested carrier image, verifies the
  copied metadata from that image with `docker create`/`docker cp`, enables and
  verifies Docker Scout repository analysis for the Docker Hub repository, runs
  Docker Scout `quickview`, `cves`, and `sbom` against the pushed Docker Hub
  tag, and publishes a GitHub release with the same docker-compatible SemVer tag
  as the carrier image.
- Before every release dispatch, pause and ask the user to provide or confirm
  the exact GitHub release tag and Docker repository/tag. The workflow requires
  that explicit version and never infers or auto-increments it. A matching
  human-readable `CHANGELOG.md` section is mandatory; the rendered notes become
  the GitHub release body and asset and are copied into the Docker carrier with
  OCI release metadata. Keep notes curated and concise: include only notable
  operator or user impact, compatibility or required upgrade actions, and a
  brief verification summary; omit commit-by-commit detail, internal workflow
  or governance narration, agent activity, and exhaustive test inventories.
  Automated disclosure validation and explicit human
  public-safety review are also mandatory. Public notes must reject credentials,
  personal or host-specific information, private infrastructure, findings,
  vulnerability mechanics, and exploit-enabling detail.
- Same-version replacement requires `replace_existing=true`, but that flag is
  not deletion authorization. Pause and obtain three fresh, separate approvals
  for the exact GitHub release, Git tag, and Docker tag before enabling the
  corresponding workflow confirmation. Earlier, blanket, same-version,
  replace, or recreate permission never carries forward. The workflow fails
  closed when any existing object lacks its own confirmation and verifies each
  authorized deletion before recreating the release.
- Before the workflow saves `runtime-images.tar.gz`, it must derive the
  required image set from the rendered Compose config and may prune only
  runner-local docker images outside that required set. Do not replace this
  with service-name hardcoding or image-specific cleanup. The archive stream
  uses bounded `docker save` retries with storage diagnostics because hosted
  runner Docker daemons can fail the archive stream transiently. On
  GitHub-hosted Linux runners, the workflow must move Docker's data root to
  `/mnt/docker-data` before the large carrier build so required images such as
  Ollama are not pulled into the small root filesystem.
- The workflow uses `DOCKERHUB_USERNAME` and `DOCKERHUB_TOKEN`; the token must
  be a docker hub access token, never an account password. No workflow in this
  repository may create GitHub deployment records. Do not add job-level
  `environment` blocks; GitHub Actions environments create deployment records.
- Before claiming installation parity, prove the targeted code path with local
  contract tests and, for release/easy-install changes, a live install or update
  run from the exact checkout/tag under test while preserving non-example env
  files.

## bioformats2raw version compatibility

- `bioformats2raw` is installed in the `omeroweb` container. The version is controlled by `BIOFORMATS2RAW_VERSION` from `env/omeroserver.env`.
- Before upgrading `bioformats2raw`, verify Java compatibility: run `bioformats2raw --version` inside the container. If the new version requires a newer Java runtime (check "class file version" errors), you must first install the required JDK in the Dockerfile.
- The base image `openmicroscopy/omero-web-standalone` ships Java 8 (class file version 52). `bioformats2raw` v0.11.x works with Java 8. Starting from v0.12.x, Java 11+ (class file version 55) is required.
- `bioformats2raw` bundles its own Bio-Formats version. Check `bioformats2raw --version` output for the bundled Bio-Formats version. This is independent of any Bio-Formats version used by OMERO.server.

## Host sandbox vs container network

- Do not keep retrying host-side `localhost` probes after one failure.
- For OMERO.web route checks, enumerate the running service's published
  bindings and verify `/webgateway/`; default endpoint docs are reference
  topology, not live probe input.
- Switch to the Docker network path from inside a running container, usually `omeroweb`, using service DNS names such as `http://loki:3100`.
- Prefer the runtime interpreter inside the OMERO.web virtualenv for container-local Python checks.

## OMERO CLI and container Python

- Never run OMERO CLI as `root` inside `omeroserver` or `omeroweb`.
- Do not use `su - <service-user>` for OMERO CLI diagnostics. The login shell
  drops the container's OMERO temp environment and can trigger plugin-loading
  errors such as `Could not find lockable tmp dir`.
- Use the service account with explicit `HOME`, `USER`, `LOGNAME`, `LNAME`,
  `USERNAME`, `TMPDIR`, `OMERO_TMPDIR`, `OMERO_TEMPDIR`, `OMERO_USERDIR`, and
  `OMERO_SESSIONDIR`, matching the startup scripts' `runuser -p -m ...`
  handoff.
- For in-container pytest with `-W error`, unset deprecated `OMERO_TEMPDIR`
  and run from a checkout or mounted test tree that includes repo-level helpers.
- For in-container Django view probes, set
  `DJANGO_SETTINGS_MODULE=omeroweb.settings`, call `django.setup()` before
  `RequestFactory`, and clean OMP job files through
  `omeroweb_omp_plugin/services/core.py` helpers `_job_path` and
  `_job_lock_path`.
- Put OMERO auth flags before the subcommand.
- Resolve the active virtualenv first. `OMERO_WEB_VENV` may be relative inside
  the container; do not assume an absolute `/opt/omero/web/venv-*` path.
  `startup/50-config.py` also accepts explicit `OMERO_WEB_OMERO_BIN`/`OMERO_BIN`,
  `OMERO_WEB_PYTHON_BIN`/`PYTHON_BIN`, and
  `OMERO_CONFIG_GLOB`/`OMERO_WEB_CONFIG_GLOB` overrides for startup
  validation, but normal probes should discover the active runtime path first.
- For OMERO.web import validation, authenticate as a regular OMERO user; the Import plugin intentionally blocks `root`.
- If repository modules are missing inside a container, switch to the runtime virtualenv instead of retrying plain `python3`.

## Multiline container probes

Prefer:

```bash
docker exec -i <container> bash -s <<'SH'
...
SH
```

Avoid deeply nested heredocs inside `docker exec ... bash -lc "..."`.

## Testing policy

- Fix production code instead of weakening tests.
- When rewriting or compacting docs or instruction files, preserve every
  required meaning. If a line-count budget must change, update tests with
  explicit phrase or behavior invariants that prove the required context still
  exists.
- Less is more: prefer fewer lines of code or docs only when tests, review, and
  repo rules prove full functional parity.
- If a repo instruction, runbook, script, or helper causes a proven avoidable
  retry/error loop, first establish the correct workflow end to end, then update
  that instruction or tool concisely with regression coverage.
- Run each test directory as a separate `pytest` invocation.
- In root-owned clones, keep `-p no:cacheprovider -W error`.
- Maintain a verification ledger with the exact command, relevant tree state,
  result, and runtime artifact. Do not repeat a passing check unless one of
  those inputs changed.
- Parallelize independent read-only gates when host resources permit. Serialize
  Docker builds and live operations that share containers, databases, OMERO
  objects, temporary paths, or persistent storage.
- Use targeted ownership-boundary checks while editing, then run the full
  required matrix once against the final tree before release.
- Tests and live verification must not assume pre-existing non-root users,
  groups, images, datasets, projects, screens, files, annotations, script IDs,
  acquisition metadata, plugin index rows, or host-specific paths. If a check
  needs one, create a deterministic disposable fixture inside that check and
  clean or uniquely isolate it. User-specified live objects are diagnostic
  probes only, not reusable regression fixtures.
- For synthetic live OMERO images, pass an iterator to
  `createImageFromNumpySeq`, reload the saved image before annotation writes,
  and assert against metadata extracted from the reloaded image rather than
  client-side labels that OMERO may not persist.
- For disposable live OMERO table fixtures, name every object with one unique
  prefix, delete the `FileAnnotation`/`Annotation` first, then re-query
  `OriginalFile` rows by that prefix before deleting any remaining files. Do
  not retry deletion of an `OriginalFile` ID captured before annotation
  deletion; OMERO may have already removed it.
- Live verification must exercise the changed mechanisms end to end after the
  relevant containers reflect the current checkout. For plugin work, include
  importability, served views/static assets, changed service paths, logs for the
  affected service, and a fresh rebuild/injection/restart path whenever runtime
  behavior can depend on container state.
- If host `pytest` cannot import Django or optional test dependencies such as
  `numpy`, `numcodecs`, or `matplotlib`, run
  `python3 tools/run_local_workflow_gates.py --setup-only` and use
  `${LOCAL_WORKFLOW_GATE_VENV:-.cache/local-workflow-gates/python-venv}/bin/python`
  for targeted pytest commands.
- `tools/run_local_workflow_gates.py` writes scanner artifacts under
  `${LOCAL_WORKFLOW_GATE_ARTIFACT_DIR:-.cache/local-workflow-gates}` and
  auto-detects the remote default branch; set `DEFAULT_BRANCH` only when local
  Super-Linter cannot resolve the repository default branch.
- If full runtime verification is blocked, use direct-module or syntax validation only as an explicit fallback and report that limitation accurately.
- After rebuilding `omeroweb`, verify existing plugin temp subtrees under `OMERO_TMP_PATH` inside the live container. `startup/10-web-bootstrap.sh` is expected to repair non-server top-level plugin trees such as `omeroweb-import/` back to the OMERO.web runtime UID before supervisord drops privileges.

## Verification order

```bash
python3 tools/lint_docs_structure.py
python3 -m unittest -v tests/test_lint_docs_structure.py
python3 -m pytest tests/ -v -p no:cacheprovider -W error
python3 -m pytest omero_plugin_common/tests/ -v -p no:cacheprovider -W error
python3 -m pytest omero_imaris_connector/tests/ -v -p no:cacheprovider -W error
python3 -m pytest omeroweb_admin_tools/tests/ -v -p no:cacheprovider -W error
python3 -m pytest omeroweb_omp_plugin/tests/ -v -p no:cacheprovider -W error
python3 -m pytest omeroweb_import/tests/ -v -p no:cacheprovider -W error
python3 -m pytest omeroweb_tools/tests/ -v -p no:cacheprovider -W error
python3 -m pytest omero_web_zarr/tests/ -v -p no:cacheprovider -W error
ruff check .
ruff format --check .
```

If the active host exposes Ruff only through the Python module entrypoint, use
`python3 -m ruff check .` and `python3 -m ruff format --check .` instead.

## Log triage order

1. Admin Tools or Loki-backed log access
2. installation transcripts under `${OMERO_DATA_PATH}/installation_logs/`
3. container logs
4. direct Docker inspection

Preferred Loki pattern:

```bash
docker exec -i <omeroweb-container> bash -s <<'SH'
set -euo pipefail
python_bin=""
: "${OMERO_WEB_ROOT:?OMERO_WEB_ROOT is required}"
if [ -n "${OMERO_WEB_VENV:-}" ]; then
  case "$OMERO_WEB_VENV" in
    /*) candidate_roots="$OMERO_WEB_VENV" ;;
    *) candidate_roots="${OMERO_WEB_ROOT}/${OMERO_WEB_VENV}" ;;
  esac
else
  candidate_roots=""
fi
for root in $candidate_roots "$OMERO_WEB_ROOT"/venv*; do
  for executable in "$root/bin/python3" "$root/bin/python"; do
    if [ -x "$executable" ]; then python_bin="$executable"; break 2; fi
  done
done
[ -n "$python_bin" ] || { echo "OMERO.web Python not found" >&2; exit 1; }
"$python_bin" - <<'PY'
import json, urllib.parse, urllib.request
params = urllib.parse.urlencode({
    "query": '{compose_service="omeroserver", log_type="internal"} |~ "(?i)error"',
    "direction": "backward",
    "start": "START_NS",
    "end": "END_NS",
    "limit": "50",
})
with urllib.request.urlopen(f"http://loki:3100/loki/api/v1/query_range?{params}", timeout=20) as response:
    print(json.loads(response.read().decode("utf-8", errors="replace")))
PY
SH
```

## Joined-session and import-thread rules

- When request-scoped helper code joins an existing end-user OMERO session, call `detachOnDestroy()` on the joined session before wrapping it in `BlitzGateway`.
- Do not reopen the importing user's live OMERO.web session inside background threads or subprocess follow-up work.
- Do not assume the `job-service` account can impersonate users with `suConn()`.
- In `omeroweb_import`, background dataset preparation and SEM-EDX follow-up attachments must use an independent admin-created user session or an already-created detached user session key. Do not route those paths through `job-service.suConn()`.
- Keep request-path dataset-target preparation light and format-agnostic.
- Keep heavy import-unit planning and CLI dry-run scans in background compatibility/import threads, not in upload HTTP handlers.
- For grouped-package naming, prefer OMERO CLI `-n` over post-import rename work when possible.
- Keep native Zarr scan timeouts long and environment-driven.
- When OMERO CLI returns non-zero, check stdout and stderr for created object IDs before declaring the import failed.

## Native Zarr and rendering notes

- `omero zarr import` is reference-based and stores the managed-store path in `Image.details.externalInfo.lsid`.
- Native Zarr metadata finalization must normalize shorthand units such as `nm` or `µm` before persisting physical sizes.
- Restage browser uploads to a durable server-readable tmp/shared-transfer location before native Zarr import; do not point native import at `_staged/`, and do not move upload or conversion work into `ManagedRepository`.
- Managed-repository native Zarr staging must treat the fully rendered
  `omero.fs.repo.path` template as the persistent handoff container, create or
  delete that rendered container plus the staged `.zarr` leaf through OMERO's
  repository API, keep the rendered template path traversal-only, and keep the
  staged `.zarr` tree service-readable; owner-only modes cause
  `PermissionError`, and raw `mkdir` under `ManagedRepository` can trigger
  `Directory exists but is not registered`.
- If a live rendered managed path exists on disk but `Repository.fileExists(...)` returns `False` while `treeList(...)` still traverses it, treat that path as stale unmanaged residue from an older helper revision rather than a healthy registered path.
- When resolving the managed-repository proxy from OMERO shared resources, do not assume `RepositoryMap.proxies` is a hash map. Live servers can expose it as a description-aligned sequence with `None` holes; pair it with `descriptions` by index when it is not mapping-like.
- Route every Zarr layout supported by the installed `omero-cli-zarr` runtime through the native path.
- For NGFF-backed images, thumbnail/render failures often surface in `master.err` from the Zarr pixel service or reader stack.
- OMERO.iviewer and OMERO.figure import `omeroweb.webgateway.marshal.imageMarshal` by value at import time. Hardened marshal overrides must patch already-imported viewer modules too.

## Security workflow reminders

- Before security-sensitive edits, read `docs/reference/ai-agent-security-prevention-playbook.md`, `docs/reference/code-scanning-resolved-findings.md`, and `docs/operations/code-scanning.md`.
- Fix root causes before considering suppressions.
- Refresh action versions from official GitHub releases or tags before touching workflow pins.
- No workflow in this repository may create GitHub deployment records. Do not
  add job-level `environment` blocks; GitHub Actions environments create
  deployment records.
