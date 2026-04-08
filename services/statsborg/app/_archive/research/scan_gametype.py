#!/usr/bin/env python3
"""Scan Xbox memory for gametype indicators during live gameplay.

Reads multiple candidate addresses via XBDM or QMP to find a reliable
gametype source. Run this DURING a live game (not at post-game screen).

Usage:
    python research/scan_gametype.py --host 172.20.0.51               # XBDM
    python research/scan_gametype.py --host 172.20.0.10 --qmp 4444    # QMP
    python research/scan_gametype.py --host 172.20.0.10 --qmp 4444 --scan  # deep scan
"""

import argparse
import struct
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from xbdm_client import XBDMClient
from qmp_client import QMPClient
from halo2_structs import GameType, GAMETYPE_NAMES

# --- Candidate addresses for gametype ---

# Known gametype locations (user-space, .data section)
CANDIDATES = {
    "xbox7887_gametype":     0x50224C,   # int32 gametype enum — "reads as zero"
    "pgcr_header_gametype":  0x56B984,   # int32 in PGCR header +0x84 — stale from prev game
    "pgcr_header_base":      0x56B900,   # PGCR Display header (0x90 bytes)
}

# Discovered areas that might contain gametype during gameplay
SCAN_REGIONS = {
    "game_state_extended":   (0x510000, 0x200),    # Empirically discovered
    "game_state_area":       (0x55C300, 0x200),    # Near PCR data
    "profile_region":        (0x53D000, 0x100),    # Player/profile data
    "near_xbox7887":         (0x502240, 0x20),     # Around xbox7887 gametype addr
}

GAMETYPE_MAP = {v: k for k, v in GameType.__members__.items() if v > 0}


def read_int32(client, addr):
    """Read a single int32 from memory."""
    data = client.read_memory(addr, 4)
    if not data or len(data) < 4:
        return None
    return struct.unpack('<I', data)[0]


def read_int16(client, addr):
    """Read a single int16 from memory."""
    data = client.read_memory(addr, 2)
    if not data or len(data) < 2:
        return None
    return struct.unpack('<H', data)[0]


def read_byte(client, addr):
    """Read a single byte from memory."""
    data = client.read_memory(addr, 1)
    if not data or len(data) < 1:
        return None
    return data[0]


def check_gametype_value(value, label):
    """Check if a value matches a known gametype enum."""
    if value is None:
        print(f"  {label}: READ FAILED")
        return
    gt_name = GAMETYPE_MAP.get(value)
    if gt_name:
        print(f"  {label}: {value} -> {gt_name} <<<")
    elif value == 0:
        print(f"  {label}: 0 (None/empty)")
    else:
        print(f"  {label}: {value} (unknown)")


def scan_for_gametype_bytes(client, start, length, label):
    """Scan a region for bytes matching known gametype enum values."""
    data = client.read_memory(start, length)
    if not data or len(data) < length:
        print(f"  {label}: READ FAILED (got {len(data) if data else 0}/{length})")
        return

    # Check for non-zero content
    non_zero = sum(1 for b in data if b != 0)
    if non_zero == 0:
        print(f"  {label} (0x{start:08X}, {length}B): ALL ZEROS")
        return

    print(f"  {label} (0x{start:08X}, {length}B): {non_zero} non-zero bytes")

    # Look for gametype values as int32
    for offset in range(0, length - 3, 4):
        val = struct.unpack_from('<I', data, offset)[0]
        if val in GAMETYPE_MAP and val > 0:
            print(f"    +0x{offset:04X} (0x{start + offset:08X}): "
                  f"int32={val} -> {GAMETYPE_MAP[val]}")

    # Look for gametype values as single bytes
    for offset in range(length):
        val = data[offset]
        if val in GAMETYPE_MAP and val > 0:
            # Only report if surrounded by zeros (isolated gametype byte)
            before = data[offset - 1] if offset > 0 else 0
            after = data[offset + 1] if offset < length - 1 else 0
            if before == 0 and after == 0:
                print(f"    +0x{offset:04X} (0x{start + offset:08X}): "
                      f"byte={val} -> {GAMETYPE_MAP[val]} (isolated)")


def scan_pgcr_header(client):
    """Dump the full PGCR Display header (0x90 bytes) looking for gametype."""
    data = client.read_memory(0x56B900, 0x90)
    if not data or len(data) < 0x90:
        print("  PGCR header: READ FAILED")
        return

    non_zero = sum(1 for b in data if b != 0)
    print(f"\n  PGCR Header (0x56B900, 0x90 = 144 bytes): {non_zero} non-zero bytes")

    if non_zero == 0:
        print("    ALL ZEROS — no active PGCR")
        return

    # Show all int32 values that match gametype
    for offset in range(0, 0x90 - 3, 4):
        val = struct.unpack_from('<I', data, offset)[0]
        if val in GAMETYPE_MAP and val > 0:
            print(f"    +0x{offset:02X} (0x{0x56B900 + offset:08X}): "
                  f"int32={val} -> {GAMETYPE_MAP[val]}")
        elif val != 0 and val < 100:
            print(f"    +0x{offset:02X} (0x{0x56B900 + offset:08X}): "
                  f"int32={val}")


def scan_wider_data_section(client):
    """Scan wider .data section for isolated gametype enum values.

    .data is 0x0046D6E0 - 0x00573858 (~1MB). We scan in 4KB chunks
    looking for int32 values matching gametype enums.
    """
    DATA_START = 0x46D6E0
    DATA_END = 0x573858
    CHUNK = 4096

    print(f"\n--- Deep scan: .data section 0x{DATA_START:08X} - 0x{DATA_END:08X} ---")
    hits = []

    addr = DATA_START
    while addr < DATA_END:
        read_len = min(CHUNK, DATA_END - addr)
        data = client.read_memory(addr, read_len)
        if not data or len(data) < read_len:
            addr += CHUNK
            continue

        for offset in range(0, len(data) - 3, 4):
            val = struct.unpack_from('<I', data, offset)[0]
            abs_addr = addr + offset
            if val in GAMETYPE_MAP and val > 0:
                # Skip known PGCR/PCR player data regions (gametype values in player structs)
                if 0x55CAF0 <= abs_addr <= 0x56CAD0 + 0x84 * 8:
                    continue
                if 0x56B990 <= abs_addr <= 0x56CAD0:
                    continue
                hits.append((abs_addr, val))

        addr += CHUNK

    if not hits:
        print("  No gametype enum matches found in .data section")
    else:
        print(f"  Found {len(hits)} matches:")
        for abs_addr, val in hits:
            print(f"    0x{abs_addr:08X}: int32={val} -> {GAMETYPE_MAP[val]}")


def main():
    parser = argparse.ArgumentParser(description="Scan for gametype in Xbox memory")
    parser.add_argument("--host", default="172.20.0.51")
    parser.add_argument("--qmp", type=int, default=None, help="QMP port (enables QMP mode)")
    parser.add_argument("--scan", action="store_true", help="Deep scan full .data section")
    args = parser.parse_args()

    # Connect
    if args.qmp:
        print(f"Connecting via QMP to {args.host}:{args.qmp}...")
        client = QMPClient(args.host, args.qmp)
        if not client.connect():
            print("QMP connection failed")
            sys.exit(1)
    else:
        print(f"Connecting via XBDM to {args.host}:731...")
        client = XBDMClient(args.host)
        if not client.connect():
            print("XBDM connection failed")
            sys.exit(1)

    print("Connected. Reading gametype candidates...\n")

    # 1. Check known gametype addresses
    print("--- Known gametype addresses ---")
    for name, addr in CANDIDATES.items():
        if name == "pgcr_header_base":
            continue  # Handled separately
        val = read_int32(client, addr)
        check_gametype_value(val, f"{name} (0x{addr:08X})")

    # Also check as byte (gametype might be stored as uint8)
    for name, addr in CANDIDATES.items():
        if name == "pgcr_header_base":
            continue
        val = read_byte(client, addr)
        if val and val != 0:
            gt_name = GAMETYPE_MAP.get(val)
            if gt_name:
                print(f"  {name} as byte: {val} -> {gt_name}")

    # 2. PGCR header dump
    scan_pgcr_header(client)

    # 3. Scan discovered regions
    print("\n--- Discovered regions ---")
    for name, (addr, length) in SCAN_REGIONS.items():
        scan_for_gametype_bytes(client, addr, length, name)

    # 4. Deep scan (optional)
    if args.scan:
        scan_wider_data_section(client)

    client.disconnect()
    print("\nDone.")


if __name__ == "__main__":
    main()
