#!/usr/bin/env python3
"""
Live memory monitor for Halo 2 stats discovery.

Monitors the memory regions where we found player names to detect
when stats populate during gameplay.

Discovered addresses (player "Default" in lobby):
- 0x53E0C0: Name with 0x90 (144) byte stride
- 0x55D790: Name near PCR with 0x1F8 (504) byte stride
"""

import argparse
import time
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from xbdm_client import XBDMClient


def hexdump_line(addr: int, data: bytes, highlight_nonzero: bool = True) -> str:
    """Format a 16-byte line as hex dump."""
    hex_parts = []
    for b in data[:16]:
        if highlight_nonzero and b != 0:
            hex_parts.append(f'{b:02X}')
        else:
            hex_parts.append(f'{b:02X}')
    hex_str = ' '.join(hex_parts)
    ascii_str = ''.join(chr(b) if 32 <= b < 127 else '.' for b in data[:16])
    return f"{addr:08X}: {hex_str:<48} {ascii_str}"


def read_player_slot(client: XBDMClient, base: int, stride: int, index: int, size: int = 64):
    """Read a player slot and return non-zero byte count."""
    addr = base + (index * stride)
    data = client.read_memory(addr, size)
    if not data:
        return None, 0
    nonzero = sum(1 for b in data if b != 0)
    return data, nonzero


def monitor_region(client: XBDMClient, name: str, base: int, stride: int, slots: int = 4):
    """Monitor a memory region for player data."""
    print(f"\n{name}")
    print(f"  Base: 0x{base:08X}, Stride: 0x{stride:X} ({stride} bytes)")
    print("-" * 70)

    for i in range(slots):
        addr = base + (i * stride)
        data = client.read_memory(addr, min(stride, 64))
        if not data:
            print(f"  Slot {i}: [READ FAILED]")
            continue

        nonzero = sum(1 for b in data if b != 0)

        # Try to extract name (UTF-16LE, first 32 bytes usually)
        try:
            name_bytes = data[:32]
            # Find null terminator
            name_end = 32
            for j in range(0, 32, 2):
                if j+1 < len(name_bytes) and name_bytes[j] == 0 and name_bytes[j+1] == 0:
                    name_end = j
                    break
            player_name = name_bytes[:name_end].decode('utf-16-le', errors='ignore').strip()
        except:
            player_name = ""

        if player_name:
            print(f"  Slot {i}: '{player_name}' ({nonzero} non-zero bytes)")
            # Show first 48 bytes as hex
            print(f"    {hexdump_line(addr, data[:16])}")
            if len(data) > 16:
                print(f"    {hexdump_line(addr+16, data[16:32])}")
            if len(data) > 32:
                print(f"    {hexdump_line(addr+32, data[32:48])}")
        elif nonzero > 0:
            print(f"  Slot {i}: [no name] ({nonzero} non-zero bytes)")
            print(f"    {hexdump_line(addr, data[:16])}")
        time.sleep(0.05)


def main():
    parser = argparse.ArgumentParser(description="Monitor Halo 2 memory for live stats")
    parser.add_argument("--host", "-H", default="127.0.0.1", help="XBDM host")
    parser.add_argument("--port", "-p", type=int, default=731, help="XBDM port")
    parser.add_argument("--loop", "-l", type=float, default=0, help="Loop interval (0=once)")
    args = parser.parse_args()

    print("=" * 70)
    print(" Halo 2 Live Stats Monitor")
    print("=" * 70)
    print(f"Connecting to {args.host}:{args.port}...")

    client = XBDMClient(args.host, args.port, read_delay=0.05)
    if not client.connect():
        print("ERROR: Failed to connect")
        sys.exit(1)

    print("Connected!\n")

    # Define regions to monitor based on our discovery
    regions = [
        # Profile region - 0x90 byte stride
        ("Profile Region (0x53E0C0, stride 0x90)", 0x53E0C0, 0x90, 4),

        # Near PCR - 0x1F8 byte stride
        ("Near PCR (0x55D790, stride 0x1F8)", 0x55D790, 0x1F8, 4),

        # PCR itself for comparison
        ("PCR Stats (0x55CAF0, stride 0x114)", 0x55CAF0, 0x114, 4),
    ]

    try:
        iteration = 0
        while True:
            iteration += 1
            print(f"\n{'='*70}")
            print(f" Scan #{iteration} - {time.strftime('%H:%M:%S')}")
            print("=" * 70)

            for name, base, stride, slots in regions:
                monitor_region(client, name, base, stride, slots)
                time.sleep(0.1)

            if args.loop <= 0:
                break

            print(f"\n[Waiting {args.loop}s... Press Ctrl+C to stop]")
            time.sleep(args.loop)

    except KeyboardInterrupt:
        print("\n[Stopped]")

    client.disconnect()


if __name__ == "__main__":
    main()
