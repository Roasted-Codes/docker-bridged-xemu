#!/bin/sh
set -e

# Disable TX checksum offloading (critical for pcap injection)
ethtool -K eth0 tx off 2>/dev/null || true

# Start hub in background
echo "Starting hub on port ${HUB_PORT:-1337}..."
python3 /app/hub.py --port ${HUB_PORT:-1337} --verbose &
HUB_PID=$!
sleep 1

# Auto-detect Xbox MAC from EEPROM file (bytes 64-69 = offset 0x40)
EEPROM_FILE="${EEPROM_FILE:-/config/emulator/iguana-eeprom.bin}"

if [ -z "$XBOX_MAC" ] && [ -f "$EEPROM_FILE" ]; then
    # Read 6 bytes at offset 64, format as MAC address
    XBOX_MAC=$(xxd -s 64 -l 6 -p "$EEPROM_FILE" | sed 's/\(..\)/\1:/g; s/:$//')
    echo "Auto-detected Xbox MAC from EEPROM: $XBOX_MAC"
fi

if [ -z "$XBOX_MAC" ]; then
    echo "XBOX_MAC not set and EEPROM not found at $EEPROM_FILE"
    echo "Run 'docker exec l2tunnel /app/l2tunnel discover eth0' to find it."
    # Keep hub running for discovery
    wait $HUB_PID
    exit 0
fi

echo "Bridging traffic for Xbox MAC: $XBOX_MAC"

# Start l2tunnel to bridge eth0 <-> hub
# -s = capture packets FROM this MAC (the emulated Xbox's outgoing traffic)
exec /app/l2tunnel tunnel eth0 -s "$XBOX_MAC" \
    0.0.0.0 0 127.0.0.1 ${HUB_PORT:-1337}
