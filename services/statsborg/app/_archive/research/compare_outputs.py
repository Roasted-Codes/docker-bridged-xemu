#!/usr/bin/env python3
"""Compare two halo2_stats.py JSON outputs field-by-field."""
import json
import sys


def compare(a, b, path=""):
    """Recursively compare two values, yielding (path, a_val, b_val) for mismatches."""
    if type(a) != type(b):
        yield (path, a, b)
    elif isinstance(a, dict):
        for key in sorted(set(list(a.keys()) + list(b.keys()))):
            yield from compare(a.get(key), b.get(key), f"{path}.{key}")
    elif isinstance(a, list):
        if len(a) != len(b):
            yield (f"{path}(len)", len(a), len(b))
        for i in range(min(len(a), len(b))):
            yield from compare(a[i], b[i], f"{path}[{i}]")
    elif a != b:
        yield (path, a, b)


def main():
    if len(sys.argv) != 3:
        print(f"Usage: {sys.argv[0]} <xbdm.json> <qmp.json>")
        sys.exit(1)

    with open(sys.argv[1]) as f:
        xbdm = json.load(f)
    with open(sys.argv[2]) as f:
        qmp = json.load(f)

    # Remove fields expected to differ
    for d in (xbdm, qmp):
        d.pop("timestamp", None)

    mismatches = list(compare(xbdm, qmp))
    if not mismatches:
        print("ALL FIELDS MATCH — XBDM and QMP produced identical results.")
    else:
        print(f"MISMATCHES FOUND: {len(mismatches)}")
        for path, a_val, b_val in mismatches:
            print(f"  {path}")
            print(f"    XBDM: {a_val}")
            print(f"    QMP:  {b_val}")


if __name__ == "__main__":
    main()
