# OMERO Container Permission Fixes - Applied Changes

## Summary of Changes

This document describes all the fixes applied to resolve the OMERO container startup permission issues.

## Problem Fixed

**Original Issue**: The `omeroserver` container was failing to start with:
```
PermissionError: [Errno 13] Permission denied: '/OMERO/certs'
```

**Root Cause**: The `/OMERO` volume mount was not writable by the container user (UID 1000).

## Solution Implemented

We implemented a **three-layer defense** to ensure permissions are always correct:

### Layer 1: Init Container (docker-compose.yml)
- **Container**: `omero-data-init`
- **When**: Runs ONCE before `omeroserver` starts
- **What**: Fixes ownership of `/OMERO` directory to UID 1000:1000
- **How**: Runs as root, sets correct permissions automatically
- **Location**: `docker-compose.yml` lines 285-325

**Benefits**:
- ✅ Works on fresh installations
- ✅ Works on existing installations
- ✅ Fixes permissions even if host directory is owned by wrong user
- ✅ No manual intervention required

### Layer 2: Startup Script (00-check-and-fix-permissions.sh)
- **When**: Runs FIRST in container startup sequence
- **What**: Verifies `/OMERO` is writable, attempts to fix if not
- **How**: Tests write permission, provides clear error messages if unfixable
- **Location**: `startup/00-check-and-fix-permissions.sh`

**Benefits**:
- ✅ Catches permission issues before they cause cryptic errors
- ✅ Provides clear, actionable error messages
- ✅ Creates `/OMERO/certs` directory proactively
- ✅ Fails fast with helpful diagnostics

### Layer 3: Certificate Script Fix (05-omero-cert-sans.sh)
- **Change**: Modified to FAIL (exit 1) when permissions are wrong
- **Original behavior**: Warned but exited successfully (exit 0)
- **New behavior**: Exits with error code 1 and clear error message
- **Location**: `startup/05-omero-cert-sans.sh` lines 59-66

**Benefits**:
- ✅ No more silent failures
- ✅ Clear error messages
- ✅ Container won't start in broken state

## Files Modified

### 1. docker-compose.yml
**Changes**:
- Added `omero-data-init` service (lines 285-325)
- Updated `omeroserver` depends_on to include `omero-data-init`

**What it does**:
```yaml
omero-data-init:
  # Runs as root (user: "0:0")
  # Fixes ownership: chown -R 1000:1000 /OMERO
  # Sets permissions: chmod -R u+rwX /OMERO
  # Creates /OMERO/certs directory
  # Runs once, then exits
```

### 2. startup/00-check-and-fix-permissions.sh (NEW)
**Purpose**: Pre-flight permission check and fix

**What it does**:
1. Checks if `/OMERO` directory exists
2. Tests if current user can write to `/OMERO`
3. If not writable, attempts to fix ownership
4. If cannot fix, provides clear error message with exact commands to run
5. Creates `/OMERO/certs` directory if missing
6. Verifies everything is writable before proceeding

**Exit codes**:
- `0`: All permissions OK, safe to proceed
- `1`: Permission error that cannot be auto-fixed (provides instructions)

### 3. startup/05-omero-cert-sans.sh
**Changes**: Lines 59-66

**Before**:
```bash
if ! ensure_cert_directory_permissions; then
    echo "[CERT] WARNING: skipping certificate regeneration..."
    exit 0  # ← PROBLEM: exits successfully even though failed!
fi
```

**After**:
```bash
if ! ensure_cert_directory_permissions; then
    echo "[CERT] ERROR: Cannot regenerate certificates - not writable."
    echo "[CERT] ERROR: This should have been fixed by 00-check-and-fix-permissions.sh"
    exit 1  # ← FIX: exits with error code
fi
```

### 4. docker/omero-server.Dockerfile
**Changes**: Added lines to copy new script

**Addition**:
```dockerfile
# Check and fix OMERO directory permissions (MUST RUN FIRST)
COPY startup/00-check-and-fix-permissions.sh /startup/00-check-and-fix-permissions.sh
RUN set -euo pipefail; \
    chown root:root /startup/00-check-and-fix-permissions.sh; \
    chmod 0555 /startup/00-check-and-fix-permissions.sh
```

## How It Works Now

### Startup Sequence

```
1. Docker Compose starts services
   ↓
2. omero-data-init runs (as root)
   ├─ Fixes ownership of /OMERO → 1000:1000
   ├─ Sets permissions → u+rwX
   ├─ Creates /OMERO/certs
   └─ Exits successfully
   ↓
3. omeroserver starts (as omero-server, UID 1000)
   ↓
4. 00-check-and-fix-permissions.sh runs
   ├─ Verifies /OMERO is writable
   ├─ Creates /OMERO/certs if missing
   └─ Exits with 0 (success)
   ↓
5. 05-omero-cert-sans.sh runs
   ├─ Checks if certificates exist
   ├─ Generates certificates if needed
   └─ Exits with 0 (success)
   ↓
6. Other startup scripts run...
   ↓
7. OMERO.server starts successfully ✓
```

### Error Handling

If permissions are still wrong (unlikely with init container):

```
1. 00-check-and-fix-permissions.sh detects issue
   ↓
2. Attempts to fix (will fail if not root)
   ↓
3. Prints CLEAR error message:
   ┌─────────────────────────────────────────────────┐
   │ [PERMISSIONS] REQUIRED ACTION ON HOST:          │
   │                                                  │
   │   sudo chown -R 1000:1000 /opt/omero/...       │
   │   sudo chmod -R u+rwX /opt/omero/...           │
   │                                                  │
   │ Then restart container:                         │
   │   docker-compose down && docker-compose up -d   │
   └─────────────────────────────────────────────────┘
   ↓
4. Exits with code 1 (failure)
   ↓
5. Container startup STOPS (fails fast)
   ↓
6. User knows EXACTLY what to do
```

## Testing the Fix

### For New Installation

```bash
# Just start the containers - permissions are handled automatically
cd /opt/omero
docker-compose up -d

# Watch the init container fix permissions
docker logs omero-data-init

# Watch omeroserver start successfully
docker logs -f omero-omeroserver-1
```

### For Existing Installation

```bash
# Stop everything
cd /opt/omero
docker-compose down

# Remove old data-init container if it exists
docker rm omero-data-init 2>/dev/null || true

# Start everything - permissions will be fixed automatically
docker-compose up -d

# Verify
docker logs omero-data-init        # Should show permission fix
docker logs omero-omeroserver-1    # Should show successful startup
```

### Manual Verification

```bash
# Check ownership of host directory
ls -ld /opt/omero/omero_data/omero_user_data
# Should show: drwxr-xr-x ... 1000 1000 ...

# Check ownership inside container
docker exec omero-omeroserver-1 ls -ld /OMERO
# Should show: drwxr-xr-x ... omero-server omero-server ...

# Check certs directory
docker exec omero-omeroserver-1 ls -ld /OMERO/certs
# Should show: drwxr-x--- ... omero-server omero-server ...

# Test write permission
docker exec omero-omeroserver-1 touch /OMERO/test.txt
docker exec omero-omeroserver-1 rm /OMERO/test.txt
# Should succeed without errors
```

## Reverting Changes (If Needed)

If for some reason you need to revert these changes:

### Remove Init Container
In `docker-compose.yml`:
1. Delete the `omero-data-init` service (lines 285-325)
2. Remove `omero-data-init` from `omeroserver` depends_on

### Remove Startup Script
In `docker/omero-server.Dockerfile`:
1. Remove the `COPY startup/00-check-and-fix-permissions.sh` section
2. Delete the file `startup/00-check-and-fix-permissions.sh`

### Revert Certificate Script
In `startup/05-omero-cert-sans.sh`:
1. Change `exit 1` back to `exit 0` on line 65

Then rebuild:
```bash
docker-compose build omeroserver
```

## Benefits of This Solution

### Automatic
- ✅ No manual permission fixes required
- ✅ Works on first start
- ✅ Works after system reboot
- ✅ Works after host OS updates

### Robust
- ✅ Three layers of defense
- ✅ Fails fast with clear messages
- ✅ Easy to debug if something goes wrong

### Safe
- ✅ Only affects /OMERO directory
- ✅ Doesn't modify other system permissions
- ✅ Runs with minimal privileges (except init container)

### Portable
- ✅ Works on any Linux distribution
- ✅ Works with any Docker setup
- ✅ Works with rootless Docker (with proper setup)

## Troubleshooting

### Init Container Fails

**Symptom**: `omero-data-init` exits with error

**Check**:
```bash
docker logs omero-data-init
```

**Common causes**:
- Volume mount missing or incorrect
- Host directory doesn't exist

**Fix**:
```bash
# Ensure directory exists on host
sudo mkdir -p /opt/omero/omero_data/omero_user_data

# Restart
docker-compose down
docker-compose up -d
```

### Permission Script Still Fails

**Symptom**: `00-check-and-fix-permissions.sh` fails even with init container

**This should never happen**, but if it does:

**Check container user**:
```bash
docker exec omero-omeroserver-1 id
# Should show: uid=1000(omero-server) gid=1000(omero-server)
```

**Check mount**:
```bash
docker exec omero-omeroserver-1 mount | grep /OMERO
# Should NOT show 'ro' (read-only)
```

**Manually fix**:
```bash
# On host
sudo chown -R 1000:1000 /opt/omero/omero_data/omero_user_data
sudo chmod -R u+rwX /opt/omero/omero_data/omero_user_data

# Restart
docker-compose restart omeroserver
```

### SELinux Issues

If you're on RHEL/CentOS/Fedora with SELinux:

```bash
# Check SELinux mode
getenforce

# Temporarily disable for testing
sudo setenforce 0

# If this fixes it, add proper SELinux context:
sudo chcon -R -t svirt_sandbox_file_t /opt/omero/omero_data/omero_user_data

# Re-enable SELinux
sudo setenforce 1
```

## Additional Notes

### Init Container Privileges

The `omero-data-init` container runs as root (`user: "0:0"`) because:
- It needs to change ownership of files that might be owned by other users
- It's a one-time operation that exits immediately
- It has `network_mode: none` for security (no network access)
- It only has access to the `/OMERO` volume, nothing else

This is a common and safe pattern for fixing volume permissions in Docker.

### Startup Script Execution Order

Scripts run in alphabetical order:
1. `00-check-and-fix-permissions.sh` ← NEW (runs first)
2. `00-reset-omero-runtime.sh` (optional, usually disabled)
3. `01-set-script-python.sh`
4. `02-ensure-python-packaging.sh`
5. `05-omero-cert-sans.sh` ← MODIFIED (fails properly now)
6. `50-*.sh` (tool installations)
7. `99-*.sh` (post-start configuration)

The `00-check-and-fix-permissions.sh` runs BEFORE all others to ensure permissions are correct.

### Why Three Layers?

**Defense in depth**:
- **Init container**: Fixes the problem before the container even starts
- **Permission script**: Catches issues if init container didn't run or failed
- **Certificate script**: Last line of defense with proper error handling

This ensures the container will either:
1. Start successfully (normal case), OR
2. Fail fast with a clear, actionable error message (problem case)

No more cryptic `AssertionError` messages!

## Summary

All permission issues are now handled automatically. The container will:
- ✅ Fix permissions on startup (via init container)
- ✅ Verify permissions before proceeding (via startup script)
- ✅ Fail fast with clear messages if something is still wrong

You should never need to manually fix permissions again!
