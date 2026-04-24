---
name: omero-runtime-verifier
description: Safe runtime-debugging workflow for OMERO Docker Extended, including Loki-first log triage, container venv discovery, and correct OMERO service-user usage.
origin: repo-local skill informed by ECC v1.10.0 workflow patterns
---

# OMERO Runtime Verifier

Use this skill for live runtime debugging, service-health checks, and container-local diagnostics.

## Mandatory procedure

1. Start with `AGENTS.md` and the relevant troubleshooting doc.
2. Use the Loki/Admin Tools path first for logs.
3. Switch to container-network probes when host `localhost` is not reachable from the agent environment.
4. Resolve the active runtime virtualenv before Python import checks.
5. Use the service account, not `root`, for OMERO CLI commands.
6. For functional OMERO or plugin changes, reconcile the canonical live root, rebuild/inject/restart affected containers, and verify they reflect the exact checkout before testing.
7. Discover mutable runtime facts from the live container and Compose state; do not hard-code published ports, container names, absolute virtualenv paths, users, or installation paths.

## Hard rules

- Never run OMERO CLI as `root` inside `omeroserver` or `omeroweb`.
- Do not use `su - <service-user>` for OMERO CLI checks. It drops the OMERO
  temp environment and can cause plugin-loading errors before the command runs.
- Pass `HOME`, `TMPDIR`, `OMERO_TMPDIR`, and `OMERO_TEMPDIR` explicitly when
  switching to the service account, matching `startup/10-server-bootstrap.sh`.
- For in-container pytest with `-W error`, unset deprecated `OMERO_TEMPDIR`
  and run from a checkout or mounted test tree that includes repo-level helpers.
- For in-container Django view probes, set
  `DJANGO_SETTINGS_MODULE=omeroweb.settings`, call `django.setup()` before
  `RequestFactory`, and clean OMP job files through
  `omeroweb_omp_plugin/services/core.py` helpers `_job_path` and
  `_job_lock_path`.
- For synthetic OMERO image fixtures, pass an iterator to
  `createImageFromNumpySeq`, reload the saved image before annotation writes,
  and compare acquisition checks with metadata extracted from that reloaded
  image.
- For disposable OMERO table fixtures, use one unique name prefix, delete the
  `FileAnnotation`/`Annotation` first, then re-query `OriginalFile` rows by
  prefix before deleting remaining files; do not retry stale file IDs captured
  before annotation deletion.
- Do not repeat a Docker-socket permission error as if it were a product failure.
- Do not trust host-shell `localhost` probes from a sandboxed agent shell.
- Discover the live OMERO.web endpoint by enumerating the running service's
  published bindings and verifying `/webgateway/`; use endpoint docs only for
  default topology context, not as a live probe source.
- Do not use plain container `python3` when the code is installed inside a virtualenv.
- Resolve `OMERO_WEB_VENV` relative to the active container working layout when
  it is not absolute; never assume a fixed OMERO.web virtualenv path.
- Prefer `docker exec -i ... <<'EOF'` patterns over heavily escaped nested heredocs.
- Do not validate stale live state. A stale or dirty live root must be cleaned or reconciled non-destructively before live verification; stop only before destructive cleanup or when env guards cannot pass.

## Correct runtime patterns

```bash
docker exec -i <container> bash -s <<'SH'
...
SH
```

```bash
docker exec <container> runuser -u <service-user> -- env HOME=<home> TMPDIR=<tmp> OMERO_TMPDIR=<tmp> OMERO_TEMPDIR=<tmp> <command>
```

## Verification targets

- service health and container status
- runtime venv path and importability
- exact-checkout live code injection, rebuild, or restart for changed services
- Loki-backed logs and diagnostics
- OMERO CLI connectivity using the correct user and flag ordering
- Celery worker/process startup behavior when relevant

## Good outcome

Runtime triage follows the repo's documented procedure once, avoids invalid probes, and produces evidence that matches the real deployment architecture.
