# OMERO Deployment - Quick Start Guide

## What Was Fixed

The OMERO container was failing due to permission issues on the `/OMERO` volume mount.

**ALL FIXES HAVE BEEN APPLIED TO THIS PROJECT.**

You can now deploy OMERO without any manual permission fixes!

## Deployment Steps

### 1. Extract or Clone This Project

```bash
# If you have the zip file
unzip omero-zmb-omp-plugin-test.zip
cd omero-zmb-omp-plugin-test
```

### 2. Load Environment Variables

```bash
# Source the installation paths
source env/installation_paths.env
```

### 3. Build and Start

```bash
# Build the custom images
docker-compose build

# Start all services
docker-compose up -d
```

### 4. Watch the Startup

```bash
# Watch the permission init container
docker logs omero-data-init

# You should see:
# ================================================
# OMERO Data Permission Initialization
# ================================================
# Setting ownership to UID 1000 (omero-server)...
# ✓ Permission initialization complete

# Watch the OMERO server start
docker logs -f omero-omeroserver-1

# You should see:
# [PERMISSIONS] ✓✓✓ All permission checks passed ✓✓✓
# [CERT] Generating certificates...
# [CERT] Certificate generation complete
# ...
# OMERO.server started successfully
```

### 5. Verify Everything is Running

```bash
# Check all containers
docker-compose ps

# All should show (healthy) status:
# - omero-omeroserver-1    (healthy)
# - omero-omeroweb-1       (healthy)
# - omero-database-1       (healthy)
# - etc.

# Check OMERO web interface
curl -I http://localhost:4090
# Should return: HTTP/1.1 200 OK
```

### 6. Access OMERO

- **OMERO.web**: http://localhost:4090
- **OMERO.server**: localhost:4064
- **Grafana Monitoring**: http://localhost:3000

Default credentials (change these!):
- Username: `root`
- Password: Check `env/omeroserver.env` for `ROOTPASS`

## What Happens Automatically

### On First Start

1. **Init Container** (`omero-data-init`):
   - Creates `/opt/omero/omero_data/omero_user_data` if missing
   - Sets ownership to UID 1000 (omero-server user)
   - Sets permissions to allow writing
   - Creates `/OMERO/certs` directory
   - Exits successfully

2. **OMERO Server**:
   - Waits for init container to complete
   - Runs `00-check-and-fix-permissions.sh`
   - Verifies permissions are correct
   - Generates SSL certificates
   - Starts OMERO.server
   - Becomes healthy ✓

3. **Other Services**:
   - OMERO.web waits for OMERO.server
   - All monitoring services start
   - System is ready to use

### On Every Restart

The init container runs again to ensure permissions are always correct.

This means:
- ✅ Works after system reboot
- ✅ Works after Docker restart
- ✅ Works after host user changes
- ✅ Always starts successfully

## Troubleshooting

### Container Won't Start

**Check the logs**:
```bash
docker-compose logs omero-omeroserver-1
```

**Look for**:
- `[PERMISSIONS]` messages - permission check results
- `[CERT]` messages - certificate generation status
- Any ERROR messages

### Permission Issues (Unlikely)

If you see permission errors despite the fixes:

```bash
# Manually fix on host
sudo chown -R 1000:1000 /opt/omero/omero_data/omero_user_data
sudo chmod -R u+rwX /opt/omero/omero_data/omero_user_data

# Restart
docker-compose down
docker-compose up -d
```

### Database Connection Issues

```bash
# Check database is running
docker-compose ps database

# Check logs
docker-compose logs database

# Verify connection from omeroserver
docker exec omero-omeroserver-1 ping -c 3 database
```

### Web Interface Not Accessible

```bash
# Check omeroweb container
docker-compose ps omeroweb
docker-compose logs omeroweb

# Check if port is in use
sudo netstat -tlnp | grep 4090

# Try accessing directly
curl http://localhost:4090
```

## Updating

### Rebuild After Changes

```bash
# Stop everything
docker-compose down

# Rebuild images
docker-compose build

# Start with fresh volumes (CAREFUL - deletes data!)
docker-compose down -v
docker-compose up -d

# Or start keeping data
docker-compose up -d
```

### Update Docker Images

```bash
# Pull latest base images
docker-compose pull

# Rebuild custom images
docker-compose build --pull

# Restart
docker-compose down
docker-compose up -d
```

## Maintenance

### View Logs

```bash
# All services
docker-compose logs -f

# Specific service
docker-compose logs -f omeroserver

# Last 100 lines
docker-compose logs --tail=100 omeroserver
```

### Restart Services

```bash
# Restart all
docker-compose restart

# Restart specific service
docker-compose restart omeroserver

# Recreate containers (keeps data)
docker-compose up -d --force-recreate
```

### Backup

```bash
# Backup OMERO data
sudo tar -czf omero-backup-$(date +%Y%m%d).tar.gz \
    /opt/omero/omero_data/omero_user_data

# Backup databases
docker exec omero-database-1 pg_dump -U omero omero > omero-db-backup-$(date +%Y%m%d).sql
docker exec omero-database_plugin-1 pg_dump -U omp-plugin omp-plugin > plugin-db-backup-$(date +%Y%m%d).sql
```

### Stop Everything

```bash
# Stop but keep containers
docker-compose stop

# Stop and remove containers (keeps volumes/data)
docker-compose down

# Stop, remove containers AND volumes (DELETES ALL DATA!)
docker-compose down -v
```

## Configuration

### Environment Files

- `env/compose.env` - Grafana credentials
- `env/installation_paths.env` - All directory paths
- `env/omeroserver.env` - OMERO.server configuration
- `env/omeroweb.env` - OMERO.web configuration
- `env/omero-celery.env` - Celery worker configuration

### Changing Passwords

Edit the files and restart:

```bash
# Edit environment file
nano env/omeroserver.env

# Restart container
docker-compose restart omeroserver
```

### Changing Ports

Edit `docker-compose.yml` and change the port mappings:

```yaml
ports:
  - "4090:4090"  # Change left side: "8080:4090" for port 8080
```

Then restart:
```bash
docker-compose down
docker-compose up -d
```

## Advanced

### Running Commands in OMERO

```bash
# OMERO CLI
docker exec -it omero-omeroserver-1 /opt/omero/server/OMERO.server/bin/omero

# As omero-server user
docker exec -it -u omero-server omero-omeroserver-1 bash

# Check OMERO version
docker exec omero-omeroserver-1 /opt/omero/server/OMERO.server/bin/omero version
```

### Monitoring

Access Grafana at http://localhost:3000

Default login (change these!):
- Username: from `env/compose.env` (`GF_SECURITY_ADMIN_USER`)
- Password: from `env/compose.env` (`GF_SECURITY_ADMIN_PASSWORD`)

### Performance Tuning

Edit `docker-compose.yml`:

```yaml
omeroserver:
  # Increase memory
  deploy:
    resources:
      limits:
        memory: 8G
      reservations:
        memory: 4G
  
  # Increase file handles
  ulimits:
    nofile:
      soft: 15000  # Increase these for large datasets
      hard: 15000
```

## Support

### Check Documentation

- See `FIXES_APPLIED.md` for detailed information about permission fixes
- See `startup/README.md` for startup script documentation (if exists)

### Get Help

If you encounter issues:

1. Check the logs: `docker-compose logs`
2. Verify permissions: `ls -ld /opt/omero/omero_data/omero_user_data`
3. Check container status: `docker-compose ps`
4. Review error messages carefully - they now include actionable instructions

### Report Issues

When reporting issues, include:
- Output of `docker-compose logs`
- Output of `docker-compose ps`
- Your environment (OS, Docker version)
- Steps to reproduce

## Success!

If you see this, everything is working:

```
$ docker-compose ps
NAME                              STATUS         
omero-alloy-1                     running (healthy)
omero-blackbox-exporter-1         running (healthy)
omero-cadvisor-1                  running (healthy)
omero-database-1                  running (healthy)
omero-database_plugin-1           running (healthy)
omero-grafana-1                   running (healthy)
omero-loki-1                      running (healthy)
omero-node-exporter-1             running (healthy)
omero-omeroserver-1               running (healthy) ← CRITICAL
omero-omeroweb-1                  running (healthy) ← CRITICAL
omero-postgres-exporter-1         running (healthy)
omero-postgres-exporter-plugin-1  running (healthy)
omero-prometheus-1                running (healthy)
omero-redis-1                     running (healthy)
omero-redis-exporter-1            running (healthy)
```

Enjoy your OMERO server! 🎉
