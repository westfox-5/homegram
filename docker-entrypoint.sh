#!/bin/sh
# Make DATA_DIR writable (bind mounts are often owned by root), then drop privileges.
set -e

DATA_DIR="${DATA_DIR:-/data}"
PUID="${PUID:-1000}"
PGID="${PGID:-1000}"

if [ "$(id -u)" = "0" ]; then
    mkdir -p "$DATA_DIR"
    if [ "$(stat -c '%u:%g' "$DATA_DIR")" != "$PUID:$PGID" ]; then
        echo "homegram: setting owner of $DATA_DIR to $PUID:$PGID"
        chown -R "$PUID:$PGID" "$DATA_DIR" \
            || echo "homegram: warning: could not chown $DATA_DIR" >&2
    fi
    exec setpriv --reuid="$PUID" --regid="$PGID" --clear-groups "$@"
fi

# Already running as a non-root user (e.g. `user:` in compose): run as is.
exec "$@"
