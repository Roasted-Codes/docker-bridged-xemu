#!/bin/sh
set -e

# Disable TX checksum offloading (critical for pcap injection)
ethtool -K eth0 tx off 2>/dev/null || true

# Start hub in background
echo "Starting hub on port ${HUB_PORT:-1337}..."
python3 /app/hub.py --port ${HUB_PORT:-1337} --verbose &
HUB_PID=$!
sleep 1

# Get the emulated Xbox MAC from environment or discover it
XBOX_MAC="${XBOX_MAC:-}"

if [ -z "$XBOX_MAC" ]; then
    echo "XBOX_MAC not set. Run 'docker exec l2tunnel /app/l2tunnel discover eth0' to find it."
    echo "Then set XBOX_MAC environment variable and restart."
    # Keep hub running for discovery
    wait $HUB_PID
    exit 0
fi

echo "Bridging traffic for Xbox MAC: $XBOX_MAC"

# Start l2tunnel to bridge eth0 <-> hub
# -s = capture packets FROM this MAC (the emulated Xbox's outgoing traffic)
exec /app/l2tunnel tunnel eth0 -s "$XBOX_MAC" \
    0.0.0.0 0 127.0.0.1 ${HUB_PORT:-1337}
