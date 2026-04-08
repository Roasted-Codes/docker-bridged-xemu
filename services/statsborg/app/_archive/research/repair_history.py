#!/usr/bin/env python3
"""One-time backfill of gametype_stats in existing history JSON files.

Scans history/*.json and adds gametype_stats labels to player records
where gametype is known but gametype_stats was never populated.

Usage:
    python research/repair_history.py --dry-run    # preview changes
    python research/repair_history.py              # apply changes
"""

import json
import glob
import os
import sys

HISTORY_DIR = os.path.join(os.path.dirname(__file__), "..", "history")

GT_LABELS = {
    "ctf": ["Flag Saves", "Flag Steals"],
    "slayer": ["Avg Life", "Best Spree"],
    "oddball": ["Ball Carrier Kills", "Kills As Carrier"],
    "koth": ["Control Time", "Time On Hill"],
    "juggernaut": ["Juggernaut Kills", "Kills As Juggernaut"],
    "territories": ["Territories Taken", "Territories Lost"],
    "assault": ["Bomb Grabs", "Bomb Carrier Kills"],
}


def repair_file(path, dry_run=False):
    """Add gametype_stats to a file if gametype is set but stats are missing.

    Returns: 'fixed', 'skipped', or 'ok'
    """
    with open(path) as f:
        data = json.load(f)

    gametype = data.get("gametype")
    if not gametype:
        return "skipped"

    # Check if any player is missing gametype_stats
    players = data.get("players", [])
    if not players:
        return "skipped"

    needs_fix = any("gametype_stats" not in p for p in players)
    if not needs_fix:
        return "ok"

    labels = GT_LABELS.get(gametype.lower())
    if not labels:
        return "skipped"

    for p in players:
        if "gametype_stats" not in p:
            vals = p.get("gametype_values", [0, 0])
            p["gametype_stats"] = {
                labels[0]: vals[0] if len(vals) > 0 else 0,
                labels[1]: vals[1] if len(vals) > 1 else 0,
            }

    if not dry_run:
        with open(path, "w") as f:
            json.dump(data, f, indent=2)

    return "fixed"


def main():
    dry_run = "--dry-run" in sys.argv

    files = sorted(glob.glob(os.path.join(HISTORY_DIR, "*.json")))
    if not files:
        print(f"No JSON files found in {HISTORY_DIR}")
        return

    fixed = skipped = ok = 0
    for path in files:
        basename = os.path.basename(path)
        try:
            result = repair_file(path, dry_run)
        except (json.JSONDecodeError, KeyError) as e:
            print(f"  ERROR  {basename}: {e}")
            continue

        if result == "fixed":
            fixed += 1
            prefix = "[DRY RUN] " if dry_run else ""
            print(f"  {prefix}FIXED  {basename}")
        elif result == "skipped":
            skipped += 1
        else:
            ok += 1

    print(f"\nSummary: {fixed} fixed, {ok} already OK, {skipped} skipped (null gametype)")
    if dry_run and fixed > 0:
        print("Run without --dry-run to apply changes.")


if __name__ == "__main__":
    main()
