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

## Hard rules

- Never run OMERO CLI as `root` inside `omeroserver` or `omeroweb`.
- Do not use `su - <service-user>` for OMERO CLI checks. It drops the OMERO
  temp environment and can cause plugin-loading errors before the command runs.
- Pass `HOME`, `TMPDIR`, `OMERO_TMPDIR`, and `OMERO_TEMPDIR` explicitly when
  switching to the service account, matching `startup/10-server-bootstrap.sh`.
- Do not repeat a Docker-socket permission error as if it were a product failure.
- Do not trust host-shell `localhost` probes from a sandboxed agent shell.
- Do not use plain container `python3` when the code is installed inside a virtualenv.
- Prefer `docker exec -i ... <<'EOF'` patterns over heavily escaped nested heredocs.

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
- Loki-backed logs and diagnostics
- OMERO CLI connectivity using the correct user and flag ordering
- Celery worker/process startup behavior when relevant

## Good outcome

Runtime triage follows the repo's documented procedure once, avoids invalid probes, and produces evidence that matches the real deployment architecture.
