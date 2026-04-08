#!/usr/bin/env python3
"""
dump_pgcr_full.py — Annotated hex dump of the full PGCR Display player struct

Reads the complete 0x114 bytes per player from PGCR Display (0x56B990+) and produces
an annotated hex dump showing all known fields and highlighting UNKNOWN bytes that may
contain betrayals, best_spree, or time_alive.

Usage:
    python research/dump_pgcr_full.py --host 172.20.0.10 --qmp 4444 [--output dump.txt]

After a game with known betrayals/best_spree values, run this script at the PGCR screen.
Compare the UNKNOWN byte values against your in-game scoreboard to see if matches.
"""

import argparse
import sys
import struct
from pathlib import Path

# Add parent to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from qmp_client import QMPClient
from xbdm_client import XBDMClient
from addresses import PGCR_DISPLAY_BASE, PGCR_DISPLAY_SIZE

# PGCR Player struct layout
FIELD_MAP = {
    0x00: ("player_name", 32, "UTF-16LE[16]", "Player name"),
    0x20: ("display_name", 32, "UTF-16LE[16]", "Display name"),
    0x40: ("score_string", 32, "UTF-16LE[16]", "Score string"),
    0x60: ("kills", 4, "int32", "Kills"),
    0x64: ("deaths", 4, "int32", "Deaths"),
    0x68: ("assists", 4, "int32", "Assists"),
    0x6C: ("suicides", 4, "int32", "Suicides"),
    0x70: ("place", 2, "int16", "Place (0-indexed)"),
    0x72: ("team", 2, "int16", "Team index"),
    0x74: ("observer", 1, "bool", "Observer/spectating flag"),
    0x78: ("rank", 2, "int16", "Halo 2 skill rank (1-50)"),
    0x7A: ("rank_verified", 2, "int16", "Rank verification status"),
    0x7C: ("medals_earned", 4, "int32", "Total medals earned (count)"),
    0x80: ("medals_earned_by_type", 4, "int32", "Medal bitmask (24-bit)"),
    0x84: ("total_shots", 4, "int32", "Total shots fired"),
    0x88: ("shots_hit", 4, "int32", "Shots hit on target"),
    0x8C: ("headshots", 4, "int32", "Headshots"),
    0x90: ("killed[0]", 4, "int32", "Kills vs player slot 0"),
    0x94: ("killed[1]", 4, "int32", "Kills vs player slot 1"),
    0x98: ("killed[2]", 4, "int32", "Kills vs player slot 2"),
    0x9C: ("killed[3]", 4, "int32", "Kills vs player slot 3"),
    0xA0: ("killed[4]", 4, "int32", "Kills vs player slot 4"),
    0xA4: ("killed[5]", 4, "int32", "Kills vs player slot 5"),
    0xA8: ("killed[6]", 4, "int32", "Kills vs player slot 6"),
    0xAC: ("killed[7]", 4, "int32", "Kills vs player slot 7"),
    0xB0: ("killed[8]", 4, "int32", "Kills vs player slot 8"),
    0xB4: ("killed[9]", 4, "int32", "Kills vs player slot 9"),
    0xB8: ("killed[10]", 4, "int32", "Kills vs player slot 10"),
    0xBC: ("killed[11]", 4, "int32", "Kills vs player slot 11"),
    0xC0: ("killed[12]", 4, "int32", "Kills vs player slot 12"),
    0xC4: ("killed[13]", 4, "int32", "Kills vs player slot 13"),
    0xC8: ("killed[14]", 4, "int32", "Kills vs player slot 14"),
    0xCC: ("killed[15]", 4, "int32", "Kills vs player slot 15"),
    0xE0: ("place_string", 32, "UTF-16LE[16]", "Place string ('1st', '2nd', etc.)"),
    0x10C: ("gametype_value0", 4, "int32", "Gametype-specific value 0"),
    0x110: ("gametype_value1", 4, "int32", "Gametype-specific value 1"),
}

# Regions marked as UNKNOWN
UNKNOWN_REGIONS = [
    (0xD0, 0xDF, "UNKNOWN[4] — 4 × int32, purpose unclear. Could contain betrayals/best_spree?"),
    (0x100, 0x10B, "UNKNOWN[3] — 2 × int32 + 1 byte + 3 pad. Could contain time_alive?"),
    (0x75, 0x77, "PADDING — alignment gap after observer flag"),
]

STRUCT_SIZE = 0x114


def format_field_line(offset, known_fields, data, hex_bytes):
    """Format a single field line with hex and interpreted values."""
    line = f"  0x{offset:02X}: "

    # Add hex bytes
    line += hex_bytes.ljust(47)  # Fixed width for alignment

    # Add interpreted values for known fields
    if offset in known_fields:
        name, size, type_, desc = known_fields[offset]
        try:
            if type_ == "UTF-16LE[16]":
                # Read UTF-16LE string, strip nulls
                raw_bytes = data[offset:offset+size]
                text = raw_bytes.decode('utf-16le', errors='ignore').rstrip('\x00')
                line += f" | {name}: {repr(text)}"
            elif type_ == "int32":
                value = struct.unpack('<I', data[offset:offset+size])[0]
                # Interpret as signed too
                signed = struct.unpack('<i', data[offset:offset+size])[0]
                line += f" | {name}: {value} (0x{value:08X})"
                if signed < 0:
                    line += f" / signed: {signed}"
            elif type_ == "int16":
                value = struct.unpack('<H', data[offset:offset+size])[0]
                signed = struct.unpack('<h', data[offset:offset+size])[0]
                line += f" | {name}: {value}"
                if signed < 0:
                    line += f" / signed: {signed}"
            elif type_ == "bool":
                value = data[offset] != 0
                line += f" | {name}: {value}"
        except Exception as e:
            line += f" | {name}: <error: {e}>"

    return line


def dump_player(client, player_index, output_file=None):
    """Dump a single player's PGCR struct."""
    addr = PGCR_DISPLAY_BASE + (player_index * PGCR_DISPLAY_SIZE)

    # Read the full struct
    try:
        data = client.read_memory(addr, STRUCT_SIZE)
    except Exception as e:
        print(f"ERROR reading player {player_index} at 0x{addr:08X}: {e}")
        return False

    if data is None or not data:
        return False  # No valid data, just skip this player

    if len(data) != STRUCT_SIZE:
        print(f"ERROR: Got {len(data)} bytes instead of {STRUCT_SIZE} for player {player_index}")
        return False

    # Check if player is valid (name is not all nulls)
    name_bytes = data[0:32]
    if name_bytes == b'\x00' * 32:
        return False  # Empty slot

    output_lines = []
    output_lines.append("")
    output_lines.append(f"{'='*100}")
    output_lines.append(f"PLAYER {player_index} — Address 0x{addr:08X}")
    output_lines.append(f"{'='*100}")
    output_lines.append("")

    # Process each byte, building annotated output
    i = 0
    while i < STRUCT_SIZE:
        # Check if this offset is in a known field
        if i in FIELD_MAP:
            name, size, type_, desc = FIELD_MAP[i]
            hex_bytes = ' '.join(f'{b:02X}' for b in data[i:i+size])
            line = format_field_line(i, FIELD_MAP, data, hex_bytes)
            output_lines.append(f"{line:120} # {desc}")
            i += size
        else:
            # Check if in unknown region
            in_unknown = False
            for start, end, unknown_desc in UNKNOWN_REGIONS:
                if start <= i <= end:
                    if i == start:
                        # Print the full unknown region at once
                        unknown_size = end - start + 1
                        hex_bytes = ' '.join(f'{b:02X}' for b in data[start:end+1])
                        line = f"  0x{start:02X}: {hex_bytes.ljust(47)}"
                        # Try to interpret as int32s
                        if start == 0xD0:
                            vals = struct.unpack('<4I', data[0xD0:0xE0])
                            line += f" | {vals[0]:08X} {vals[1]:08X} {vals[2]:08X} {vals[3]:08X}"
                        elif start == 0x100:
                            vals = struct.unpack('<2I', data[0x100:0x108])
                            line += f" | {vals[0]:08X} {vals[1]:08X} + byte:{data[0x108]:02X}"
                        output_lines.append(f"{line:120} # {unknown_desc}")
                        in_unknown = True
                    i = end + 1
                    break

            if not in_unknown:
                # Regular padding or gap
                hex_bytes = ' '.join(f'{b:02X}' for b in data[i:i+1])
                line = f"  0x{i:02X}: {hex_bytes.ljust(47)}"
                output_lines.append(f"{line:120} # (padding)")
                i += 1

    output_lines.append("")

    result = '\n'.join(output_lines)

    if output_file:
        with open(output_file, 'a') as f:
            f.write(result)
    else:
        print(result)

    return True


def main():
    parser = argparse.ArgumentParser(
        description="Annotated hex dump of PGCR Display player structures"
    )
    parser.add_argument('--host', default='172.20.0.51', help='XBDM/QMP host')
    parser.add_argument('--qmp', type=int, help='QMP port (use instead of XBDM)')
    parser.add_argument('--xbdm-port', type=int, default=731, help='XBDM port')
    parser.add_argument('--timeout', type=int, default=5, help='Connection timeout')
    parser.add_argument('--output', help='Write to file instead of stdout')

    args = parser.parse_args()

    # Connect
    if args.qmp:
        client = QMPClient(args.host, args.qmp, timeout=args.timeout)
    else:
        client = XBDMClient(args.host, args.xbdm_port, timeout=args.timeout)

    # Clear output file if specified
    if args.output:
        Path(args.output).unlink(missing_ok=True)

    # Dump all valid players
    player_count = 0
    for i in range(16):
        if dump_player(client, i, args.output):
            player_count += 1

    msg = f"\nDumped {player_count} players to {args.output if args.output else 'stdout'}"
    if args.output:
        with open(args.output, 'a') as f:
            f.write(msg + "\n")
    else:
        print(msg)


if __name__ == '__main__':
    main()
