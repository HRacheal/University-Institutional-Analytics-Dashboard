#!/bin/sh
# Starts the dashboard as the unprivileged "app" user.
# Hosted persistent disks are often mounted root-owned, so when started as root this makes UIAD_VAR_DIR writable
# for "app" first, then drops privileges. Listens on 0.0.0.0:$PORT (Render sets PORT).
set -eu
VAR_DIR="${UIAD_VAR_DIR:-/var/data}"
mkdir -p "$VAR_DIR"
CMD="uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --workers 1 --proxy-headers --forwarded-allow-ips=* --no-server-header"
if [ "$(id -u)" = "0" ]; then
  chown app:app "$VAR_DIR"
  export HOME=/home/app
  exec setpriv --reuid=app --regid=app --init-groups -- $CMD    # environment is kept
fi
exec $CMD
