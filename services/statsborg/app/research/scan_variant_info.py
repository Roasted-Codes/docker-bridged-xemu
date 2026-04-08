#!/usr/bin/env python3
"""Scan Xbox physical RAM via QMP to locate the variant_info struct.

Searches for UTF-16LE variant name strings and ASCII map content paths
in physical memory regions. Can be repurposed to find other game data
structures by changing the search signatures.

Usage:
    python research/scan_variant_info.py [--host HOST] [--qmp PORT]
    python research/scan_variant_info.py --scan-only
    python research/scan_variant_info.py --search "Team Slayer"
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from qmp_client import QMPClient

# Confirmed physical addresses (discovered 2026-03-28)
CONFIRMED = {
    "variant_name":     0x036295F4,  # UTF-16LE[16], game variant display name
    "gametype_byte":    0x03629634,  # variant_name + 0x40, single byte enum
    "map_content_path": 0x03629550,  # ASCII, format: t:\$C\<title_id>\<map_name>
}

# Known candidate physical addresses (for re-scanning if addresses shift)
CANDIDATES = [
    ("Confirmed (2026-03-28)",                    0x036295F4),
    ("HaloCaster-derived (0x5C000 + 0x35AD0EC)",  0x036090EC),
    ("Old StatsBorg (incorrect)",                  0x036060EC),
]

# Regions to scan
SCAN_REGIONS = [
    ("HaloCaster region", 0x3500000, 0x3700000, "physical"),
    ("User-space .data",  0x46D6E0,  0x573858,  "va"),
]

GAMETYPE_NAMES = {
    0: "None", 1: "CTF", 2: "Slayer", 3: "Oddball", 4: "KOTH",
    7: "Juggernaut", 8: "Territories", 9: "Assault",
}


def read_variant_info(client):
    """Read variant info from confirmed addresses. Quick check."""
    data = client._read_physical(CONFIRMED["variant_name"], 0x50)
    if not data or len(data) < 0x50:
        return None

    try:
        vname = data[0:32].decode('utf-16-le').rstrip('\x00')
        vname = ''.join(c for c in vname if 0x20 <= ord(c) < 0xE000).strip()
    except Exception:
        vname = ""

    gt = data[0x40]

    map_data = client._read_physical(CONFIRMED["map_content_path"], 0xA4)
    map_name = ""
    if map_data:
        try:
            path = map_data.split(b'\x00')[0].decode('ascii')
            parts = path.replace('\\', '/').split('/')
            map_name = parts[-1] if parts else ""
        except Exception:
            pass

    return {"variant": vname, "gametype": gt, "map": map_name}


def scan_for_string(client, target_str, start, end, encoding="utf-16-le"):
    """Search a physical memory region for a string."""
    target = target_str.encode(encoding)
    hits = []
    chunk = 8192
    addr = start

    while addr < end:
        data = client._read_physical(addr, chunk + 256)
        if data:
            idx = 0
            while True:
                pos = data.find(target, idx)
                if pos == -1:
                    break
                hit_addr = addr + pos
                hits.append(hit_addr)
                ctx = data[max(0, pos - 32):pos + 64]
                print(f"  0x{hit_addr:08X}: {ctx[:80].hex()}")
                idx = pos + 1
        addr += chunk
        if addr % 0x100000 == 0:
            pct = (addr - start) * 100 // (end - start)
            print(f"\r  Scanning: {pct}%", end="", flush=True)

    print(f"\r  Done. {len(hits)} hit(s).          ")
    return hits


def scan_region_physical(client, start, end, sig=b"scenarios", chunk_size=4096):
    """Scan physical memory for a byte signature."""
    hits = []
    total = end - start
    addr = start

    while addr < end:
        data = client._read_physical(addr, chunk_size + 256)
        if not data:
            addr += chunk_size
            continue

        pos = 0
        while True:
            idx = data.find(sig, pos)
            if idx == -1:
                break
            hit_addr = addr + idx
            hits.append(hit_addr)
            ctx = data[max(0, idx - 16):idx + 48].split(b'\x00')[0]
            print(f"  0x{hit_addr:08X}: {ctx.decode('ascii', errors='replace')}")
            pos = idx + 1

        addr += chunk_size
        pct = min(100, (addr - start) * 100 // total)
        print(f"\r  Scanning: {pct}%  (0x{addr:08X})", end="", flush=True)

    print(f"\r  Done. {len(hits)} hit(s).                    ")
    return hits


def main():
    parser = argparse.ArgumentParser(description="Scan for variant_info struct via QMP")
    parser.add_argument("--host", default="localhost", help="QMP host")
    parser.add_argument("--qmp", type=int, default=4444, help="QMP port")
    parser.add_argument("--scan-only", action="store_true", help="Skip quick check, full scan")
    parser.add_argument("--search", type=str, help="Search for a specific UTF-16LE string in RAM")
    args = parser.parse_args()

    print(f"Connecting to QMP at {args.host}:{args.qmp}...")
    client = QMPClient(args.host, args.qmp)
    if not client.connect():
        print("ERROR: Failed to connect to QMP")
        sys.exit(1)
    print("Connected!\n")

    # Custom string search mode
    if args.search:
        print(f"Searching for \"{args.search}\" (UTF-16LE) in physical RAM...")
        print("=" * 60)
        for name, start, end, _ in SCAN_REGIONS:
            print(f"\n[{name}] 0x{start:08X}-0x{end:08X}")
            scan_for_string(client, args.search, start, end)
        return

    # Quick check: read confirmed addresses
    if not args.scan_only:
        print("=" * 60)
        print("QUICK CHECK: Confirmed addresses")
        print("=" * 60)
        result = read_variant_info(client)
        if result and (result["variant"] or result["map"]):
            print(f"  Variant:  \"{result['variant']}\"")
            print(f"  Gametype: {result['gametype']} ({GAMETYPE_NAMES.get(result['gametype'], '?')})")
            print(f"  Map:      \"{result['map']}\"")
            print("\n  Confirmed addresses are working.")
            return
        else:
            print("  Confirmed addresses returned empty. Running full scan...\n")

    # Full scan: search for candidate addresses
    print("=" * 60)
    print("FULL SCAN: Searching HaloCaster region for map paths")
    print("=" * 60)

    for name, start, end, mode in SCAN_REGIONS:
        if mode != "physical":
            continue
        print(f"\n[{name}] 0x{start:08X}-0x{end:08X}")
        scan_region_physical(client, start, end)

    print("\nDone.")


if __name__ == "__main__":
    main()
