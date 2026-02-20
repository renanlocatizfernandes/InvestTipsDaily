#!/bin/sh
# Fix ownership of mounted volumes (needed for bind mounts on Docker Desktop)
chown -R appuser:appuser /app/data 2>/dev/null || true

# Drop to non-root user and exec the main command
exec su -s /bin/sh appuser -c "$(echo "$@")"
