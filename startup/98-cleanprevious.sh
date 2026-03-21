#!/usr/bin/env bash
# Remove the stale django pid file left by unclean shutdowns.

set -euo pipefail

pid_file="${OMERO_WEB_DJANGO_PIDFILE:-/opt/omero/web/OMERO.web/var/django.pid}"
rm -f "${pid_file}"
