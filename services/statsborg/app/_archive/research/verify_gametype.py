#!/usr/bin/env python3
"""Systematic gametype address verification.

Play a game of each gametype, end it, then run this script to check
which memory addresses correctly identify the gametype.

Usage:
    # After ending a CTF game, at the post-game screen:
    python research/verify_gametype.py --qmp 4444 --expect ctf

    # Via XBDM:
    python research/verify_gametype.py --expect slayer

    # Print results from all rounds:
    python research/verify_gametype.py --summary

Valid gametype names: ctf, slayer, oddball, koth, juggernaut, territories, assault
"""

import argparse
import json
import os
import struct
import sys
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from xbdm_client import XBDMClient
from qmp_client import QMPClient
from halo2_structs import GameType

LOG_FILE = os.path.join(os.path.dirname(__file__), "gametype_verification.json")

GAMETYPE_LOOKUP = {
    "ctf": 1, "slayer": 2, "oddball": 3, "koth": 4,
    "juggernaut": 7, "territories": 8, "assault": 9,
}
ID_TO_NAME = {v: k.upper() for k, v in GAMETYPE_LOOKUP.items()}
ID_TO_NAME[0] = "NONE"

# Addresses under test
ADDR_PROFILE = 0x53D004
ADDR_PGCR_HEADER = 0x56B984
ADDR_XBOX7887 = 0x50224C
ADDR_PGCR_PLAYER0 = 0x56B990


def read_int32(client, addr):
    data = client.read_memory(addr, 4)
    if not data or len(data) < 4:
        return None
    return struct.unpack('<I', data)[0]


def check_addr(client, addr, expected_id, label, width=22):
    """Read an address, compare to expected, print PASS/FAIL."""
    val = read_int32(client, addr)
    if val is None:
        tag = "READ FAIL"
        match = False
    elif val == expected_id:
        tag = "PASS"
        match = True
    else:
        name = ID_TO_NAME.get(val, f"?({val})")
        tag = f"FAIL -> {name}"
        match = False

    name = ID_TO_NAME.get(val, str(val)) if val is not None else "?"
    print(f"  {label:{width}s} (0x{addr:08X}): {val} -> {name:12s}  {tag}")
    return {"addr": f"0x{addr:08X}", "value": val, "match": match}


def read_player0(client):
    """Read Player 0 cross-validation data from PGCR Display."""
    data = client.read_memory(ADDR_PGCR_PLAYER0, 0x114)
    if not data or len(data) < 0x114:
        return None

    name_raw = data[0:32]
    try:
        name = name_raw.decode('utf-16-le').rstrip('\x00')
    except UnicodeDecodeError:
        name = ""

    if not name or not all(0x20 <= ord(c) <= 0x7E for c in name):
        return None

    kills = struct.unpack_from('<i', data, 0x60)[0]
    deaths = struct.unpack_from('<i', data, 0x64)[0]
    score_str = data[0x40:0x60].decode('utf-16-le', errors='replace').rstrip('\x00')
    medals = struct.unpack_from('<I', data, 0x80)[0]
    val0 = struct.unpack_from('<i', data, 0x10C)[0]
    val1 = struct.unpack_from('<i', data, 0x110)[0]

    ctf_bits = bool((medals >> 18) & 0x7)
    assault_bits = bool((medals >> 21) & 0x7)

    return {
        "name": name, "kills": kills, "deaths": deaths,
        "score_string": score_str, "val0": val0, "val1": val1,
        "medals_ctf": ctf_bits, "medals_assault": assault_bits,
    }


def run_verification(client, expected_name, expected_id):
    """Run one verification round."""
    print(f"\n{'='*60}")
    print(f"  GAMETYPE VERIFICATION: expect {expected_name.upper()} ({expected_id})")
    print(f"{'='*60}\n")

    # Check the three candidate addresses
    result_profile = check_addr(client, ADDR_PROFILE, expected_id, "gametype_profile")
    result_pgcr = check_addr(client, ADDR_PGCR_HEADER, expected_id, "pgcr_header")
    result_xbox = check_addr(client, ADDR_XBOX7887, expected_id, "xbox7887")

    # Cross-validation from player data
    p0 = read_player0(client)
    if p0:
        print(f"\n  Player 0: \"{p0['name']}\"  K:{p0['kills']} D:{p0['deaths']}")
        print(f"  Score string: \"{p0['score_string']}\"")
        print(f"  Gametype values: val0={p0['val0']}  val1={p0['val1']}")
        print(f"  Medal CTF bits: {'SET' if p0['medals_ctf'] else 'no'}"
              f"   Medal Assault bits: {'SET' if p0['medals_assault'] else 'no'}")
    else:
        print("\n  Player 0: NOT POPULATED (is the PGCR visible?)")

    # Build log entry
    entry = {
        "timestamp": datetime.now().isoformat(),
        "expected": expected_name,
        "expected_id": expected_id,
        "gametype_profile": result_profile,
        "pgcr_header": result_pgcr,
        "xbox7887": result_xbox,
    }
    if p0:
        entry["player0_name"] = p0["name"]
        entry["player0_vals"] = [p0["val0"], p0["val1"]]
        entry["player0_score_string"] = p0["score_string"]
        entry["player0_medals_ctf"] = p0["medals_ctf"]
        entry["player0_medals_assault"] = p0["medals_assault"]

    # Append to log
    log = []
    if os.path.exists(LOG_FILE):
        with open(LOG_FILE) as f:
            try:
                log = json.load(f)
            except json.JSONDecodeError:
                log = []
    log.append(entry)
    with open(LOG_FILE, 'w') as f:
        json.dump(log, f, indent=2)

    print(f"\n  Result logged to {LOG_FILE}")
    print(f"  Total rounds logged: {len(log)}")

    # Quick verdict
    passes = sum(1 for r in [result_profile, result_pgcr, result_xbox] if r["match"])
    print(f"\n  {passes}/3 addresses matched expected gametype.\n")


def print_summary():
    """Print summary table from all logged rounds."""
    if not os.path.exists(LOG_FILE):
        print("No verification data found. Run some rounds first.")
        return

    with open(LOG_FILE) as f:
        log = json.load(f)

    if not log:
        print("Log file is empty.")
        return

    print(f"\n{'='*72}")
    print(f"  GAMETYPE VERIFICATION SUMMARY  ({len(log)} rounds)")
    print(f"{'='*72}\n")

    # Header
    print(f"  {'Round':<6} {'Expected':<14} {'Profile':<14} {'PGCR Hdr':<14} {'xbox7887':<14}")
    print(f"  {'-----':<6} {'--------':<14} {'-------':<14} {'--------':<14} {'--------':<14}")

    profile_correct = 0
    pgcr_correct = 0
    xbox_correct = 0

    for i, entry in enumerate(log, 1):
        expected = entry["expected"].upper()

        def fmt(result):
            val = result.get("value")
            name = ID_TO_NAME.get(val, str(val)) if val is not None else "?"
            ok = "OK" if result.get("match") else "X"
            return f"{name} ({ok})"

        p = fmt(entry["gametype_profile"])
        h = fmt(entry["pgcr_header"])
        x = fmt(entry["xbox7887"])

        print(f"  {i:<6} {expected:<14} {p:<14} {h:<14} {x:<14}")

        if entry["gametype_profile"].get("match"):
            profile_correct += 1
        if entry["pgcr_header"].get("match"):
            pgcr_correct += 1
        if entry["xbox7887"].get("match"):
            xbox_correct += 1

    total = len(log)
    print(f"\n  {'TOTALS':<6} {'':<14} {profile_correct}/{total:<12} {pgcr_correct}/{total:<12} {xbox_correct}/{total:<12}")

    # Verdict
    print()
    if profile_correct == total:
        print("  >>> gametype_profile (0x53D004) is RELIABLE across all tested gametypes!")
    elif profile_correct > pgcr_correct and profile_correct > xbox_correct:
        print(f"  >>> gametype_profile (0x53D004) is the BEST candidate ({profile_correct}/{total})")
    else:
        print("  >>> No single address is fully reliable. Review the data above.")
    print()


def main():
    parser = argparse.ArgumentParser(
        description="Verify gametype detection addresses",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="Valid gametypes: " + ", ".join(sorted(GAMETYPE_LOOKUP.keys())),
    )
    parser.add_argument("--host", default="172.20.0.10")
    parser.add_argument("--qmp", type=int, default=None)
    parser.add_argument("--expect", type=str, default=None,
                        help="Expected gametype (ctf, slayer, oddball, koth, juggernaut, territories, assault)")
    parser.add_argument("--summary", action="store_true", help="Print summary of all logged rounds")
    parser.add_argument("--reset", action="store_true", help="Clear the verification log")
    args = parser.parse_args()

    if args.reset:
        if os.path.exists(LOG_FILE):
            os.remove(LOG_FILE)
            print("Verification log cleared.")
        return

    if args.summary:
        print_summary()
        return

    if not args.expect:
        print("ERROR: --expect is required. Specify the gametype you just played.")
        print("  Valid: " + ", ".join(sorted(GAMETYPE_LOOKUP.keys())))
        sys.exit(1)

    expected_name = args.expect.lower()
    if expected_name not in GAMETYPE_LOOKUP:
        print(f"ERROR: Unknown gametype '{args.expect}'")
        print("  Valid: " + ", ".join(sorted(GAMETYPE_LOOKUP.keys())))
        sys.exit(1)

    expected_id = GAMETYPE_LOOKUP[expected_name]

    # Connect
    if args.qmp:
        client = QMPClient(args.host, args.qmp)
        if not client.connect():
            print("QMP connection failed")
            sys.exit(1)
    else:
        client = XBDMClient(args.host)
        if not client.connect():
            print("XBDM connection failed")
            sys.exit(1)

    try:
        run_verification(client, expected_name, expected_id)
    finally:
        client.disconnect()


if __name__ == "__main__":
    main()
