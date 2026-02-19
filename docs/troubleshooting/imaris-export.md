# Troubleshooting Imaris Export

## Symptoms

- export job remains in `STARTED`/`RUNNING` without completion,
- endpoint returns script-not-found or processor errors,
- download link never appears,
- repeated Celery poll logs with no terminal state.

## Diagnostic Steps

### 1) Validate Celery configuration visibility

```bash
docker compose exec omeroweb env | rg -n "OMERO_IMS_CELERY_(QUEUE|BROKER|BACKEND)"
```

### 2) Validate worker activity

```bash
docker compose logs --since=10m omeroweb
docker compose exec omeroweb tail -n 200 /opt/omero/web/logs/imaris-celery.out.log
docker compose exec omeroweb tail -n 200 /opt/omero/web/logs/imaris-celery.err.log
```

### 3) Validate script processor configuration (admin session)

```bash
docker compose exec omeroserver /opt/omero/server/OMERO.server/bin/omero config get omero.scripts.processors
docker compose exec omeroserver /opt/omero/server/OMERO.server/bin/omero config get omero.server.nodedescriptors
```

### 4) Validate script registration

```bash
docker compose exec omeroserver /opt/omero/server/OMERO.server/bin/omero script list
docker compose exec omeroserver tail -n 200 /opt/omero/server/OMERO.server/var/log/register-official-scripts.log
```

## Common Root Causes

- worker not running,
- queue mismatch between producer and consumer,
- script processors disabled,
- script not registered,
- session privilege mismatch for configuration introspection.

## Recovery Actions

1. Align queue and broker settings across services.
2. Restart OMERO.web worker and OMERO.server.
3. Recheck script registration and processor count.
4. Re-run a test export with async status polling.
