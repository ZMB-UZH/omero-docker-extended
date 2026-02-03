# Imaris Connector: Script Processor Troubleshooting

This guide focuses on diagnosing repeated `NoProcessorAvailable` retries and
`SecurityViolation: Cannot read configuration: omero.scripts.processors` errors.

## Symptoms

You may see:

- Repeated retries in `omeroweb` logs: `No OMERO script processor slot available`.
- `SecurityViolation: Cannot read configuration: omero.scripts.processors`.
- `omero.NoProcessorAvailable` in `Blitz-0.log`.

## Root causes to check

1. **Script processors not running**: OMERO.server requires script processors to
   execute scripts. If none are running, every script start will fail.
2. **Processor count set to 0**: `omero.scripts.processors=0` disables processors.
3. **Non-admin session**: The configuration value is restricted to admin sessions,
   so non-admin users receive `SecurityViolation` when trying to read it.
4. **Leaked ScriptProcess handles**: If clients never detach script handles, slots
   can be exhausted.

## Diagnostic commands (Docker Compose)

> Replace `<compose>` with your compose binary (`docker compose` or `docker-compose`).

### 1) Confirm processor configuration (admin-only)

```bash
<compose> exec omeroserver \
  /opt/omero/server/OMERO.server/bin/omero config get omero.scripts.processors
```

Expected: a positive integer (>= 1). If `0`, set a value and restart:

```bash
<compose> exec omeroserver \
  /opt/omero/server/OMERO.server/bin/omero config set omero.scripts.processors 2
<compose> restart omeroserver
```

### 2) Check that script processors are running

```bash
<compose> exec omeroserver ps -ef | rg -i "omero.*script"
```

If no script processes are listed, ensure the server starts them (and that
`omero.scripts.processors` is not zero).

### 3) Verify script list availability (admin account)

```bash
<compose> exec omeroserver \
  /opt/omero/server/OMERO.server/bin/omero script list
```

### 4) Inspect recent server/web logs

```bash
<compose> logs --since=10m omeroserver
<compose> logs --since=10m omeroweb
```

## Notes

- `SecurityViolation: Cannot read configuration: omero.scripts.processors` does
  **not** necessarily indicate a missing configuration; it can mean the session
  lacks admin privileges to read server configuration.
- If you are using a non-admin account in Imaris, configuration access will be
  denied even though script execution may still be possible once processors are
  running.
- Repeated `Unregistered servant: ProcessorCallback/...` messages in
  `Blitz-0.log` are expected when ScriptProcess handles are detached or cleaned
  up after starting scripts. These are cleanup logs and not a failure by
  themselves.
