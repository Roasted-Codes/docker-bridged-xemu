#!/usr/bin/env python3
"""
Memory diff monitor - captures baseline and shows changes.

Usage:
1. Run with --baseline while in lobby to capture initial state
2. Start a game and get a kill
3. Run without --baseline to see what changed
"""

import argparse
import pickle
import sys
import time
from pathlib import Path
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from xbdm_client import XBDMClient


BASELINE_FILE = Path("memory_baseline.pkl")

# Regions to monitor (name, base, size)
# Expanded regions for live stats discovery
REGIONS = [
    # Original profile regions
    ("Profile_0x53E0C0", 0x53E0C0, 0x90),   # Player 0 profile
    ("Profile_0x53E150", 0x53E150, 0x90),   # Player 1 profile

    # Discovered player index area - 16 players * 0x170 stride
    ("PlayerArray_0x5345D0", 0x5345D0, 0x1700),  # Full 16-player array

    # Broader session area (0x530000 - 0x540000 range)
    ("Session_0x534000", 0x534000, 0x2000),  # 8KB session area

    # Near PCR regions
    ("NearPCR_0x55D790", 0x55D790, 0x1F8),  # Player 0 near PCR
    ("NearPCR_0x55D988", 0x55D988, 0x1F8),  # Player 1 near PCR

    # PCR regions (for comparison, populate post-game)
    ("PCR_P0", 0x55CAF0, 0x114),            # PCR player 0
    ("PCR_P1", 0x55CC04, 0x114),            # PCR player 1

    # Wider area around PCR
    ("PCR_Extended", 0x55C000, 0x2000),     # 8KB around PCR

    # Game state pointers area (from map file)
    ("GameState_0x510000", 0x510000, 0x2000),  # 8KB game state area
]


def read_all_regions(client: XBDMClient):
    """Read all monitored regions."""
    data = {}
    for name, base, size in REGIONS:
        result = client.read_memory(base, size)
        if result:
            data[name] = (base, result)
        time.sleep(0.05)
    return data


def save_baseline(data):
    """Save baseline to file."""
    with open(BASELINE_FILE, 'wb') as f:
        pickle.dump(data, f)
    print(f"Baseline saved to {BASELINE_FILE}")


def load_baseline():
    """Load baseline from file."""
    if not BASELINE_FILE.exists():
        return None
    with open(BASELINE_FILE, 'rb') as f:
        return pickle.load(f)


def compare_regions(baseline, current):
    """Compare baseline to current and show differences."""
    print("\n" + "=" * 70)
    print(" MEMORY DIFFERENCES")
    print("=" * 70)

    total_changes = 0

    for name, (base, cur_data) in current.items():
        if name not in baseline:
            print(f"\n{name}: [NEW REGION]")
            continue

        old_base, old_data = baseline[name]
        if old_base != base:
            print(f"\n{name}: [BASE ADDRESS CHANGED!]")
            continue

        # Find differences
        changes = []
        for i in range(min(len(old_data), len(cur_data))):
            if old_data[i] != cur_data[i]:
                changes.append((i, old_data[i], cur_data[i]))

        if changes:
            print(f"\n{name} (0x{base:08X}): {len(changes)} byte(s) changed")
            print("-" * 70)

            # Group consecutive changes
            i = 0
            while i < len(changes):
                start_offset = changes[i][0]
                # Collect up to 16 consecutive/nearby bytes
                group_end = i
                while group_end + 1 < len(changes) and changes[group_end + 1][0] - changes[group_end][0] <= 2:
                    group_end += 1

                # Show this group
                line_start = (start_offset // 16) * 16
                line_end = ((changes[group_end][0] // 16) + 1) * 16

                for line_offset in range(line_start, min(line_end, len(cur_data)), 16):
                    old_hex = []
                    new_hex = []
                    for j in range(16):
                        idx = line_offset + j
                        if idx < len(old_data) and idx < len(cur_data):
                            ob = old_data[idx]
                            nb = cur_data[idx]
                            if ob != nb:
                                old_hex.append(f"[{ob:02X}]")
                                new_hex.append(f"[{nb:02X}]")
                            else:
                                old_hex.append(f" {ob:02X} ")
                                new_hex.append(f" {nb:02X} ")

                    addr = base + line_offset
                    print(f"  0x{addr:08X} OLD: {''.join(old_hex)}")
                    print(f"  0x{addr:08X} NEW: {''.join(new_hex)}")

                i = group_end + 1

            # Interpret some common offsets
            for offset, old_val, new_val in changes:
                # Check for likely stat fields (ushort at even offsets)
                if offset % 2 == 0 and offset + 1 < len(changes):
                    # Check if next byte also changed
                    next_changes = [(o, ov, nv) for o, ov, nv in changes if o == offset + 1]
                    if next_changes:
                        old_word = old_data[offset] | (old_data[offset+1] << 8)
                        new_word = cur_data[offset] | (cur_data[offset+1] << 8)
                        if new_word != old_word:
                            print(f"    Offset 0x{offset:02X}: {old_word} -> {new_word} (ushort)")

            total_changes += len(changes)

    if total_changes == 0:
        print("\nNo changes detected.")
    else:
        print(f"\nTotal: {total_changes} byte(s) changed")

    return total_changes


def main():
    parser = argparse.ArgumentParser(description="Memory diff monitor")
    parser.add_argument("--host", "-H", default="127.0.0.1")
    parser.add_argument("--port", "-p", type=int, default=731)
    parser.add_argument("--baseline", "-b", action="store_true",
                        help="Capture baseline (run in lobby)")
    args = parser.parse_args()

    print("=" * 70)
    print(" Memory Diff Monitor")
    print("=" * 70)

    client = XBDMClient(args.host, args.port, read_delay=0.05)
    if not client.connect():
        print("ERROR: Failed to connect")
        sys.exit(1)

    print("Connected!\n")

    current = read_all_regions(client)
    print(f"Read {len(current)} regions")

    if args.baseline:
        save_baseline(current)
        print("\nBaseline captured. Now:")
        print("  1. Start a game")
        print("  2. Get a kill or die")
        print("  3. Run this script without --baseline to see changes")
    else:
        baseline = load_baseline()
        if baseline is None:
            print("ERROR: No baseline found. Run with --baseline first.")
            sys.exit(1)
        compare_regions(baseline, current)

    client.disconnect()


if __name__ == "__main__":
    main()
