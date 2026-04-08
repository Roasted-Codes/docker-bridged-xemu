#!/usr/bin/env python3
"""Cross-reference all gametype snapshots to find universal addresses.

Loads snapshot .data bins for all 7 gametypes, checks every int32-aligned
offset for the correct gametype enum value, and reports addresses that
match ALL snapshots. Missing snapshots are skipped with a warning.

Usage:
    python research/crossref_snapshots.py
    python research/crossref_snapshots.py --haloc   # also scan HaloCaster region
"""

import argparse
import json
import os
import struct

SNAPSHOT_DIR = os.path.join(os.path.dirname(__file__), "snapshots")

# Expected gametype enum values for each snapshot (all 7 gametypes)
EXPECTED = {
    "slayer":      2,
    "ctf":         1,
    "oddball":     3,
    "koth":        4,
    "juggernaut":  7,
    "territories": 8,
    "assault":     9,
}

GAMETYPE_NAMES = {
    0: "None", 1: "CTF", 2: "Slayer", 3: "Oddball", 4: "KOTH",
    7: "Juggernaut", 8: "Territories", 9: "Assault",
}


def load_snapshot(label):
    """Load a snapshot's data section and metadata."""
    meta_path = os.path.join(SNAPSHOT_DIR, f"{label}_meta.json")
    data_path = os.path.join(SNAPSHOT_DIR, f"{label}_data.bin")

    if not os.path.exists(meta_path) or not os.path.exists(data_path):
        return None, None

    with open(meta_path) as f:
        meta = json.load(f)
    with open(data_path, 'rb') as f:
        data = f.read()

    return meta, data


def load_haloc_snapshot(label):
    """Load a snapshot's HaloCaster region."""
    haloc_path = os.path.join(SNAPSHOT_DIR, f"{label}_haloc.bin")
    if not os.path.exists(haloc_path):
        return None
    with open(haloc_path, 'rb') as f:
        return f.read()


def main():
    parser = argparse.ArgumentParser(description="Cross-reference gametype snapshots")
    parser.add_argument("--haloc", action="store_true", help="Also scan HaloCaster region")
    args = parser.parse_args()

    # Load all snapshots
    snapshots = {}
    for label in EXPECTED:
        meta, data = load_snapshot(label)
        if meta is None:
            print(f"WARNING: Missing snapshot for '{label}', skipping")
            continue
        snapshots[label] = {"meta": meta, "data": data}
        va_start = meta["regions"]["data_section"]["va_start"]
        print(f"  Loaded {label}: {len(data)} bytes, VA 0x{va_start:08X}, "
              f"expect gametype={EXPECTED[label]} ({GAMETYPE_NAMES.get(EXPECTED[label], '?')})")

    if len(snapshots) < 2:
        print("ERROR: Need at least 2 snapshots to cross-reference")
        return

    # Verify all snapshots have same VA start and compatible sizes
    va_starts = {l: s["meta"]["regions"]["data_section"]["va_start"] for l, s in snapshots.items()}
    if len(set(va_starts.values())) != 1:
        print(f"WARNING: VA starts differ: {va_starts}")
    va_base = list(va_starts.values())[0]

    min_size = min(len(s["data"]) for s in snapshots.values())
    labels = list(snapshots.keys())

    print(f"\n{'='*70}")
    print(f"  CROSS-REFERENCE: {len(snapshots)} snapshots, {min_size} bytes each")
    print(f"  VA range: 0x{va_base:08X} - 0x{va_base + min_size:08X}")
    print(f"{'='*70}\n")

    # === INT32 scan (4-byte aligned) ===
    print("Scanning int32-aligned offsets...")
    perfect_matches = []
    partial_matches = []  # match 4 out of 5

    for offset in range(0, min_size - 3, 4):
        values = {}
        all_match = True
        match_count = 0

        for label in labels:
            val = struct.unpack_from('<I', snapshots[label]["data"], offset)[0]
            values[label] = val
            expected = EXPECTED[label]
            if val == expected:
                match_count += 1
            else:
                all_match = False

        if all_match:
            va = va_base + offset
            perfect_matches.append((offset, va, values))
        elif match_count >= len(labels) - 1:
            va = va_base + offset
            partial_matches.append((offset, va, values, match_count))

    # === BYTE scan (every byte, looking for isolated gametype values) ===
    print("Scanning individual bytes...")
    byte_perfect = []

    for offset in range(min_size):
        all_match = True
        values = {}
        for label in labels:
            val = snapshots[label]["data"][offset]
            values[label] = val
            if val != EXPECTED[label]:
                all_match = False
                break
        if all_match:
            # Check if it's isolated (surrounding bytes are stable)
            stable_context = True
            for label in labels:
                if offset > 0:
                    before = snapshots[label]["data"][offset - 1]
                    if before != snapshots[labels[0]]["data"][offset - 1]:
                        stable_context = False
                if offset < min_size - 1:
                    after = snapshots[label]["data"][offset + 1]
                    if after != snapshots[labels[0]]["data"][offset + 1]:
                        stable_context = False

            va = va_base + offset
            # Skip if this is part of an int32 match (we'll report those separately)
            aligned_offset = (offset // 4) * 4
            is_int32 = any(m[0] == aligned_offset for m in perfect_matches)
            if not is_int32:
                byte_perfect.append((offset, va, values, stable_context))

    # === Report Results ===
    print(f"\n{'='*70}")
    print(f"  RESULTS")
    print(f"{'='*70}")

    print(f"\n  PERFECT INT32 MATCHES ({len(perfect_matches)} addresses):")
    print(f"  These hold the correct gametype enum as int32 in ALL {len(snapshots)} snapshots.\n")

    if perfect_matches:
        # Header
        header = f"  {'VA':<12s} {'Offset':<10s}"
        for label in labels:
            header += f" {label:>12s}"
        print(header)
        print(f"  {'-'*12} {'-'*10}" + (" " + "-"*12) * len(labels))

        for offset, va, values in perfect_matches:
            line = f"  0x{va:08X}  0x{offset:06X} "
            for label in labels:
                v = values[label]
                name = GAMETYPE_NAMES.get(v, "?")
                line += f" {v:>4d} ({name:>4s})"
            print(line)

            # Show context (8 bytes before and after from first snapshot)
            ctx_start = max(0, offset - 8)
            ctx_end = min(min_size, offset + 12)
            ctx = snapshots[labels[0]]["data"][ctx_start:ctx_end]
            hex_str = " ".join(f"{b:02X}" for b in ctx)
            target_pos = offset - ctx_start
            pointer = "   " * target_pos + "^^^^^^^^"
            print(f"             context: {hex_str}")
            print(f"                      {pointer}")
    else:
        print("  (none)")

    if partial_matches:
        print(f"\n  PARTIAL INT32 MATCHES ({len(partial_matches)} addresses):")
        print(f"  These match {len(labels)-1}/{len(labels)} snapshots.\n")

        header = f"  {'VA':<12s} {'Offset':<10s}"
        for label in labels:
            header += f" {label:>12s}"
        print(header)
        print(f"  {'-'*12} {'-'*10}" + (" " + "-"*12) * len(labels))

        for offset, va, values, count in partial_matches[:30]:
            line = f"  0x{va:08X}  0x{offset:06X} "
            for label in labels:
                v = values[label]
                expected = EXPECTED[label]
                name = GAMETYPE_NAMES.get(v, "?")
                marker = " " if v == expected else "!"
                line += f" {v:>4d} ({name:>4s}){marker}"
            print(line)

    if byte_perfect:
        print(f"\n  PERFECT BYTE MATCHES (not part of int32, {len(byte_perfect)} addresses):")
        for offset, va, values, stable in byte_perfect[:20]:
            stability = "stable-ctx" if stable else "unstable-ctx"
            print(f"  0x{va:08X} (offset 0x{offset:06X}): [{stability}]")

    # === HaloCaster region ===
    if args.haloc:
        print(f"\n{'='*70}")
        print(f"  HALOC REGION CROSS-REFERENCE")
        print(f"{'='*70}\n")

        haloc_data = {}
        for label in labels:
            hdata = load_haloc_snapshot(label)
            if hdata is None:
                print(f"  WARNING: Missing HaloCaster snapshot for '{label}'")
                continue
            haloc_data[label] = hdata
            print(f"  Loaded {label} haloc: {len(hdata)} bytes")

        if len(haloc_data) >= 2:
            haloc_min = min(len(d) for d in haloc_data.values())
            haloc_base = 0x3500000  # physical base of HaloCaster region

            haloc_perfect = []
            for offset in range(0, haloc_min - 3, 4):
                all_match = True
                values = {}
                for label in haloc_data:
                    val = struct.unpack_from('<I', haloc_data[label], offset)[0]
                    values[label] = val
                    if val != EXPECTED[label]:
                        all_match = False
                        break
                if all_match:
                    phys = haloc_base + offset
                    haloc_perfect.append((offset, phys, values))

            print(f"\n  PERFECT INT32 MATCHES in HaloCaster region: {len(haloc_perfect)}")
            for offset, phys, values in haloc_perfect[:30]:
                kernel_va = phys + 0x80000000
                vals = ", ".join(f"{values[l]}" for l in labels if l in values)
                print(f"    phys 0x{phys:08X} (kernel VA 0x{kernel_va:08X}): {vals}")

    # === Summary ===
    print(f"\n{'='*70}")
    print(f"  SUMMARY")
    print(f"{'='*70}")
    print(f"  Snapshots analyzed: {len(snapshots)} ({', '.join(labels)})")
    print(f"  Perfect int32 matches: {len(perfect_matches)}")
    print(f"  Partial int32 matches: {len(partial_matches)}")
    print(f"  Perfect byte-only matches: {len(byte_perfect)}")

    if perfect_matches:
        print(f"\n  CANDIDATE ADDRESSES FOR UNIVERSAL GAMETYPE DETECTION:")
        for offset, va, values in perfect_matches:
            print(f"    0x{va:08X}")


if __name__ == "__main__":
    main()
