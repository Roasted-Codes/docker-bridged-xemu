#!/bin/bash
set -e

# Start web viewer in background
python -u pgcr_server.py "${WEB_PORT:-8080}" &

# Run watch mode as PID 1 (exec replaces shell — Docker restart policy monitors this process)
# halo2_stats.py handles connection retries internally via QMPClient.connect_with_retry()
if [ "${WATCH_MODE:-xbdm}" = "qmp" ]; then
    exec python -u halo2_stats.py \
        --host "${QMP_HOST:-172.20.0.49}" \
        --qmp "${QMP_PORT:-4444}" \
        --watch \
        --history-dir /app/history
else
    exec python -u halo2_stats.py \
        --host "${XBDM_HOST:-172.20.0.51}" \
        --port "${XBDM_PORT:-731}" \
        --watch \
        --history-dir /app/history
fi
