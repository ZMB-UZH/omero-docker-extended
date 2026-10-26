# AI Agent Runtime Playbook

Deep operational guidance for AI Agents. `AGENTS.md` should route here instead of duplicating these details.

## Git ownership and local clones

- Deployment clones are often root-owned. `git` write operations can fail until ownership is fixed.
- If a read-only `git` command reports dubious ownership, use `git -c safe.directory=<repo> ...` for inspection.
- Do not `chown` bind-mounted data directories such as `postgresdb/`, `omero_data/`, or `omero_temp/` to a non-service user.
- Worktrees and related clones can exist under `/tmp/omero-*`. Search them before declaring a commit missing.
- Develop, commit, push, and verify on the current remote default branch unless the user explicitly names another branch. Resolve it dynamically; never create feature branches, PR branches, temporary remote branches, or draft PRs just to run workflows or scanner checks.
- Follow the [GitHub publication contract](ai-agent-task-contracts.md#github-publication):
  the official GitHub connector verifies its authenticated account and repository
  write permission, creates commits using GitHub defaults, and updates the expected
  branch head without force. No local identity overrides or AI co-author trailers.
- Local Git inspection and fetches remain useful for source verification. They do
  not prove connector identity or permission and cannot replace connector publication.
- If the connector cannot perform the required write, stop publication and repair
  that connection. Do not switch to a PAT push helper or another account.

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
- Match the active release's hardening and flattening settings when rebuilding candidates. A plain Compose build of older revisions can skip hardening; compare effective OS/Python package inventories before deployment and never accept a candidate that silently downgrades them.
- Verify flattening with the real Docker round-trip gate, not generated-text
  assertions alone. Preserve literal environment values, labels and paths;
  JSON escaping does not preserve Dockerfile `ENV` or `LABEL` values. Copy the
  source filesystem without executing its deferred `ONBUILD` instructions.
- Before replacement, verify entrypoint and configuration readability as the
  image's non-root runtime user. Checkout permissions can survive Docker COPY;
  set required runtime modes explicitly in the Dockerfile, and test restrictive
  source permissions without changing operator data or configuration.
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

- **Dots (`.`) become single underscores (`_`)**: `omero.web.debug` → `CONFIG_omero_web_debug`
- **Underscores (`_`) become DOUBLE underscores (`__`)**: `omero.web.session_cookie_age` → `CONFIG_omero_web_session__cookie__age`

Examples:

| OMERO config property                          | Docker env variable                                      |
| ---------------------------------------------- | -------------------------------------------------------- |
| `omero.web.session_engine`                     | `CONFIG_omero_web_session__engine`                       |
| `omero.web.session_cookie_age`                 | `CONFIG_omero_web_session__cookie__age`                  |
| `omero.web.session_expire_at_browser_close`    | `CONFIG_omero_web_session__expire__at__browser__close`   |
| `omero.web.csrf_trusted_origins`               | `CONFIG_omero_web_csrf__trusted__origins`                |
| `omero.web.application_server.port`            | `CONFIG_omero_web_application__server_port`              |

**Common mistake**: using single underscores where doubles are required. `CONFIG_omero_web_session_engine` (wrong) vs `CONFIG_omero_web_session__engine` (correct). The single-underscore version silently creates a different (nonexistent) config property.

## Docker image rebuilds: cached vs no-cache

- Before overwriting a mutable image tag or replacing its container, retain an
  inspectable rollback image or verified export and the corresponding baseline
  scan evidence. A container's recorded image ID alone is not a retained image;
  verify the saved reference independently before proceeding.
- `docker compose build <service>` reuses unchanged layers. Changed build ARG values invalidate dependent instructions; changed base-image digests and COPY inputs also invalidate their dependent layers. Verify the resolved inputs and installed versions rather than assuming a cache hit means stale code.
- Build every changed image recipe with its reviewed defaults before publication.
  Lint and Buildx `--check` do not resolve package pins or execute image startup.
  The deployment workflow builds the TLS issuer and verifies fresh certificate
  issuance, readiness and idempotence on isolated mounts.
- A plain Compose build does not enable optional dependency-update arguments.
  Match the reviewed installer or release hardening profile explicitly, then
  verify installed package versions and `pip check` in the resulting images.
  Do not change operator-owned env files to select a verification build profile.
- Before full-image analysis, check available memory, swap, scratch space, and
  scanner concurrency. Large image indexing belongs on a suitably sized build
  host, not an already busy application host. Docker exports allow analysis
  elsewhere without rebuilding; verify immutable image identities before and
  after export, and retain complete SBOMs and advisory reports. An interrupted
  scan is incomplete, never a clean result.
- Treat a scanner memory-exhaustion kill as a stop-and-relocate condition.
  Do not repeat indexing on the application host with only a different Go
  garbage-collection target: `GOMEMLIMIT` is soft and does not establish a hard
  resident-memory boundary. Use isolated analysis compute with an enforced
  process or cgroup memory limit and headroom for other workloads. Stream
  immutable image archives off the deployment host when needed; preserve the
  complete inventory and verify archive hashes and filesystem-layer identities.
  Do not change global VM or application memory settings to accommodate analysis.
- Runtime-image analysis creates private per-image scratch under its selected
  `--output-dir`, not global temporary storage. Choose an output filesystem with
  room for image export and unpacked layers; a small RAM-backed temporary
  directory is unsuitable. Scratch is removed on success and failure without
  pruning shared caches or touching other output files.
- `docker compose build --no-cache <service>` reruns every layer. Use it when refreshing externally resolved packages without a changed cache input, or when investigating a demonstrated stale layer, not automatically for every version change. See [Docker cache invalidation](https://docs.docker.com/build/cache/invalidation/).
- If a live installation build starts transferring GBs of context, stop before
  `up` and inspect `.dockerignore`; generated runtime roots such as
  `omero_data/`, `omero_temp/`, `postgresdb/`, `node_modules/`, and
  `.project-pull.*/` must stay excluded from build contexts.
- Build ARGs such as `OMERO_DROPBOX_VERSION`, `BIOFORMATS2RAW_VERSION`,
  `BIOFORMATS2RAW_SHA256`, and `BIOFORMATS_SHA256` come from
  `env/omeroserver.env`. `docker-compose.yml`
  and `docker/<service>.Dockerfile` fail closed when those values are absent
  instead of silently falling back to in-code defaults.

### Final deployment cleanup

Derive required images from the guarded, rendered Compose configuration and
active containers, including configured optional profiles and one-shot helpers.
Compare this set with the daemon's image IDs and tags, temporary containers, and
builder caches. Retain rollback artifacts until live checks pass. Obtain the
required separate approval for each pre-existing object before removal; do not
use a broad prune as a substitute for inventory reconciliation.
The release-runner pruning helper rejects an empty required-image inventory
before contacting Docker; do not bypass that check for cleanup.

A fresh-install image inventory is not a data reset. Preserve operator env
files, database and application volumes, bind-mounted data, shared transfer and
temporary roots, permissions, and unrelated workloads. Remove only reviewed
superseded images and owned verification artifacts. Finish with a second image
inventory, unchanged persistent mounts/configuration, and healthy services.

### Registry cleanup with every release

With every release, reconcile Docker Hub Image Management after publication,
restoration, or replacement. This is a required release-maintenance step, not
optional housekeeping. A successful release workflow or matching tag count does
not establish that the registry is free of obsolete objects.

1. Save a private before-state: all published releases and their recorded carrier
   digests, all registry tags, and every Image Management page. If an API cannot
   enumerate untagged objects, inspect the authenticated UI; a tag list is not an
   equivalent inventory. Do not start cleanup while another publication is active.
2. Resolve every retained index recursively. Preserve referenced image manifests,
   shared children, configurations, layers, SBOM/provenance attestations,
   signatures, and subject/referrer relationships. An untagged object or an old
   last-pulled date does not prove it is unused. Retain uncertain objects.
3. Compare the full inventory with that protected reference graph. Review each
   candidate by its full digest, with fresh separate approval for each deletion.
   Recheck tags and references immediately before deletion; stop if they changed.
   Remove obsolete parents before their children, and remove a child only after
   confirming that no remaining object references it. Never delete blobs directly,
   select all untagged entries, or use an object-count target as a cleanup rule.
4. Verify all retained release tags, digests, manifest graphs, and referenced
   blobs again. Reconcile every Image Management page with the before-state and
   approved deletions. Preserve the evidence privately and report any unresolved
   candidates; do not claim cleanup is complete while it remains unverified.

For registry cleanup, count release tags separately from OCI manifest objects.
An untagged child referenced by a retained index is not stale. One release can
require an index, a platform image, and one or more untagged attestations.
Never use the registry UI's object count as a deletion target; preserve every
needed component. Follow Docker's
[Image Management](https://docs.docker.com/docker-hub/repos/manage/hub-images/manage/)
and [Registry API](https://docs.docker.com/reference/api/registry/latest/)
documentation; use bounded readback after an uncertain deletion response rather
than blindly repeating a destructive request.

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
- Validate the actual repository changelog with the shared release-note renderer
  before dispatch, not only synthetic test fixtures. Every dated release section
  needs its matching previous-tag comparison link, and the `Unreleased` link
  must start at the newest release. The prebuilt carrier contract suite checks
  every committed release section for these publication prerequisites.
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

- `bioformats2raw` is installed in the `omeroweb` container. Its version and
  official release digest are controlled by `BIOFORMATS2RAW_VERSION` and
  `BIOFORMATS2RAW_SHA256` from `env/omeroserver.env`; the Compose guard rejects
  a stale generated `.env` mirror before any build or deployment.
- Before upgrading `bioformats2raw`, verify Java compatibility: run `bioformats2raw --version` inside the container. If the new version requires a newer Java runtime (check "class file version" errors), you must first install the required JDK in the Dockerfile.
- Inspect the selected base image's Java runtime. `bioformats2raw` v0.11.x supports Java 8; v0.12.x and later require Java 11+ (class file version 55).
- `bioformats2raw` bundles its own Bio-Formats version. Check `bioformats2raw --version` output for the bundled Bio-Formats version. This is independent of any Bio-Formats version used by OMERO.server.

## Host sandbox vs container network

- Do not keep retrying host-side `localhost` probes after one failure.
- For OMERO.web route checks, enumerate the running service's published
  bindings and verify `/webgateway/`; default endpoint docs are reference
  topology, not live probe input.
- Switch to the Docker network path from inside a running container, usually `omeroweb`, using service DNS names such as `https://loki:3100` and the configured public CA. Never bypass peer verification.
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
- Programmatic `omero.cli.CLI()` use requires `loadplugins()` before `invoke()`; constructing the object does not register commands. Verify a real command, not only a mocked invocation.
- `ParametersI.add()` requires an OMERO `RType`. Wrap string lists as `rlist([rstring(value), ...])` and integers as `rlong(value)`; raw Python values can pass permissive mocks but fail Ice serialization.
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
- For threaded UI changes, test window closure during an active worker and while
  a worker awaits a queued callback. Require bounded completion, no late widget
  access, and no unhandled thread exceptions; preserve authenticated sessions
  during unrelated network failures.
- Run Linux verification as an unprivileged account. Filesystem tests need unique,
  test-owned temporary roots and real readback where persistence is the contract.
  Never repair a failing test by changing ownership of shared or operator data.
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
import json, os, ssl, urllib.parse, urllib.request
context = ssl.create_default_context(cafile=os.environ["ADMIN_TOOLS_TLS_CA_FILE"])
params = urllib.parse.urlencode({
    "query": '{compose_service="omeroserver", log_type="internal"} |~ "(?i)error"',
    "direction": "backward",
    "start": "START_NS",
    "end": "END_NS",
    "limit": "50",
})
with urllib.request.urlopen(f"https://loki:3100/loki/api/v1/query_range?{params}", context=context, timeout=20) as response:
    print(json.loads(response.read().decode("utf-8", errors="replace")))
PY
SH
```

## Joined-session and import-thread rules

### Historical session-regression gate

- Review the relevant commit history and current call sites before changing
  authentication, session storage, cookies, cleanup, or gateway ownership.
  Historical anchors include `ae0af493` and `f5602308` (joined-session teardown),
  `ba3f2adf` and `fa42c43f` (independent background work), `bf00c075`
  (Redis-backed sessions and cookie/cache lifetime), and `c1116a20`
  (export cleanup). History identifies mechanisms; it does not prove current behavior.
- A TCP connection reset is not proof of logout. Distinguish transport errors,
  HTTP redirects, expired cookies, missing cache entries, and invalid OMERO sessions.
- XT background health checks must retain the client, cookies and selections
  during outages or ordinary permission failures, and retry without replaying
  credentials or writes. Only an explicit authentication rejection permits a
  local session reset. Test the installed OMERO API's response: HTTP 403 alone
  is not proof, and a login path in a URL query is not a login redirect.
- Include manual XT Refresh in that boundary: its historical retry path called
  reauthentication after any error. Retry browser reads using the original
  session; never infer expiry from a transport or permission failure. Check
  stale refresh callbacks cannot clear a newer connection.
- Treat borrowed gateways as non-owning: `detachOnDestroy()` does not make
  `BlitzGateway.close()` non-destructive. Use `close(hard=False)` for reconnection
  and local cleanup. Only explicitly owned job sessions may be terminated.
- Never retry a failed soft close with a hard close or an unspecified default.
  Verify the installed gateway API; test doubles must match that supported
  signature instead of inventing compatibility requirements. Keep cleanup failures visible.
- Live session checks must preserve the original browser cookie and server
  session across browsing, rendering, monitoring, imports, exports, and background
  cleanup. Include an independent idle session beyond the historical five-minute
  cache timeout, browser-context reopening without login, and logout isolation.
  Reauthentication or replacing the cookie invalidates a continuity claim.
- Redis-backed sessions are not disposable cache. Never flush session keys during
  cleanup. Redis eviction, expiry, restart, and replacement need explicit data-loss
  analysis and isolated lifecycle tests; a web-container restart test does not
  prove Redis or OMERO.server restart persistence.
- Preserve regression evidence and test the identified cause, including error
  cleanup paths. Do not generalize one import-format result to every login flow.

### Ownership and background work

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
