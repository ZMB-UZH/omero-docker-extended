# OMERO ZMB OMP Plugin - FIXED VERSION

## ⚠️ IMPORTANT: This Version Includes Permission Fixes

This is the **FIXED** version of the OMERO deployment that automatically handles all permission issues.

**What was fixed**: The container was failing with `PermissionError: [Errno 13] Permission denied: '/OMERO/certs'`

**How it's fixed**: Automatic permission initialization - no manual intervention required!

---

## 🚀 Quick Start

```bash
# 1. Extract and navigate
cd omero-zmb-omp-plugin-test

# 2. Load environment variables
source env/installation_paths.env

# 3. Build and start (permissions handled automatically!)
docker-compose build
docker-compose up -d

# 4. Verify it's working
docker-compose ps
# All services should show (healthy)

# 5. Access OMERO.web
# Open browser: http://localhost:4090
```

**That's it!** The permission issues are handled automatically.

---

## 📖 Documentation

### Start Here
- **DEPLOYMENT_GUIDE.md** - Complete deployment and usage guide
- **FIXES_APPLIED.md** - Detailed explanation of all fixes
- **CHANGELOG.md** - Complete list of changes

### What's Fixed

The original container was failing with permission errors. This version includes:

1. **Init Container** - Automatically fixes /OMERO permissions before startup
2. **Permission Check Script** - Verifies permissions and provides clear errors
3. **Certificate Script Fix** - Proper error handling (no more silent failures)

**Result**: Container starts reliably every time!

---

## ✅ Files Changed

- `docker-compose.yml` - Added omero-data-init service
- `docker/omero-server.Dockerfile` - Added permission check script
- `startup/00-check-and-fix-permissions.sh` - NEW automatic permission fixer
- `startup/05-omero-cert-sans.sh` - Fixed to fail properly on errors

See **CHANGELOG.md** for complete details.

---

## 🔧 System Requirements

- Docker Engine 20.10+
- Docker Compose 1.27.0+
- Linux-based OS
- 4GB RAM minimum (8GB recommended)
- 20GB free disk space

**No manual permission setup required!**

---

## 📊 Services Included

- OMERO.server (with custom scripts and plugins)
- OMERO.web (with Imaris connector, admin tools)
- PostgreSQL (main + plugin databases)
- Redis (caching)
- Grafana + Prometheus + Loki (monitoring)
- Various exporters and metrics collectors

---

## 🐛 Troubleshooting

### Container Not Starting

```bash
# Check logs
docker-compose logs omero-omeroserver-1

# Look for [PERMISSIONS] and [CERT] messages
```

### Still Have Permission Issues?

```bash
# This shouldn't be needed, but just in case:
sudo chown -R 1000:1000 /opt/omero/omero_data/omero_user_data
docker-compose restart omeroserver
```

### More Help

See **DEPLOYMENT_GUIDE.md** for complete troubleshooting.

---

## 📝 Configuration

Environment files in `env/` directory:
- `installation_paths.env` - Directory paths
- `omeroserver.env` - OMERO.server settings (passwords here!)
- `omeroweb.env` - OMERO.web settings
- `omero-celery.env` - Celery worker config
- `compose.env` - Grafana credentials

**CHANGE DEFAULT PASSWORDS IN PRODUCTION!**

---

## 🎉 What's Different From Original

**Before** (Original):
- ❌ Required manual `sudo chown` commands
- ❌ Cryptic error messages
- ❌ Container failed to start

**After** (This Version):
- ✅ Automatic permission handling
- ✅ Clear error messages
- ✅ Reliable startup
- ✅ Production ready

---

## 📞 Support

- Check **DEPLOYMENT_GUIDE.md** for usage
- Check **FIXES_APPLIED.md** for technical details
- Check **CHANGELOG.md** for all changes
- View logs: `docker-compose logs -f`

---

**Version**: Fixed (2025-02-11)  
**Status**: Production Ready  
**Fixes**: Complete automatic permission handling
