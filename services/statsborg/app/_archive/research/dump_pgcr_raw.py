"""
Quick memory dump of PGCR regions for struct analysis.
Dumps raw hex of: PGCR header, first few player records, and team data.
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from xbdm_client import XBDMClient

HOST = "172.20.0.51"

# Regions to dump
REGIONS = {
    "PGCR Header (0x56B900, 0x90 bytes)": (0x56B900, 0x90),
    "Player 0 (0x56B990, 0x114 bytes)": (0x56B990, 0x114),
    "Player 1 (0x56BAA4, 0x114 bytes)": (0x56BAA4, 0x114),
    "Player 2 (0x56BBB8, 0x114 bytes)": (0x56BBB8, 0x114),
    "Player 3 (0x56BCCC, 0x114 bytes)": (0x56BCCC, 0x114),
    "Player 4 (0x56BDE0, 0x114 bytes)": (0x56BDE0, 0x114),
    "Team 0 (0x56CAD0, 0x84 bytes)": (0x56CAD0, 0x84),
    "Team 1 (0x56CB54, 0x84 bytes)": (0x56CB54, 0x84),
    "Team 2 (0x56CBD8, 0x84 bytes)": (0x56CBD8, 0x84),
    "Team 3 (0x56CC5C, 0x84 bytes)": (0x56CC5C, 0x84),
}


def hexdump(data, base_addr, width=16):
    """Format bytes as a hex dump with offset, hex, and ASCII columns."""
    lines = []
    for i in range(0, len(data), width):
        chunk = data[i:i+width]
        hex_part = " ".join(f"{b:02X}" for b in chunk)
        ascii_part = "".join(chr(b) if 0x20 <= b < 0x7F else "." for b in chunk)
        lines.append(f"  {base_addr + i:08X}  {hex_part:<{width*3}}  {ascii_part}")
    return "\n".join(lines)


def main():
    print(f"Connecting to XBDM at {HOST}:731...")
    client = XBDMClient(HOST)
    client.connect()
    print("Connected!\n")

    output_lines = []

    for label, (addr, length) in REGIONS.items():
        print(f"Reading {label}...")
        try:
            data = client.read_memory(addr, length)
            if data:
                dump = hexdump(data, addr)
                header = f"=== {label} ==="
                output_lines.append(header)
                output_lines.append(dump)
                output_lines.append("")
                print(dump)
                print()
            else:
                msg = f"=== {label} === NO DATA"
                output_lines.append(msg)
                print(msg)
        except Exception as e:
            msg = f"=== {label} === ERROR: {e}"
            output_lines.append(msg)
            print(msg)

    client.disconnect()

    # Save to file
    outfile = "pgcr_dump.txt"
    with open(outfile, "w") as f:
        f.write("\n".join(output_lines))
    print(f"\nSaved to {outfile}")


if __name__ == "__main__":
    main()
