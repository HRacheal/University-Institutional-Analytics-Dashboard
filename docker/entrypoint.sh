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
  # Secret files may be readable by root only: hand the account-import file to "app" privately (container-local, 0400).
  if [ -n "${UIAD_IMPORT_ACCOUNTS_FILE:-}" ] && [ -f "$UIAD_IMPORT_ACCOUNTS_FILE" ]; then
    install -d -o app -g app -m 0700 /run/uiad
    install -o app -g app -m 0400 "$UIAD_IMPORT_ACCOUNTS_FILE" /run/uiad/accounts.json
    export UIAD_IMPORT_ACCOUNTS_FILE=/run/uiad/accounts.json
  fi
  export HOME=/home/app
  exec setpriv --reuid=app --regid=app --init-groups -- $CMD    # environment is kept
fi
exec $CMD
