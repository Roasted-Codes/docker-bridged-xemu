#!/usr/bin/env python3
"""
Search for player name in memory to locate session data structures.
"""

import argparse
import time
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from xbdm_client import XBDMClient


def search_for_string(client: XBDMClient, search: str, start: int, end: int, chunk_size: int = 4096):
    """Search memory region for UTF-16LE string."""
    # Convert search string to UTF-16LE bytes
    search_bytes = search.encode('utf-16-le')
    print(f"Searching for '{search}' as UTF-16LE: {search_bytes.hex()}")
    print(f"Region: 0x{start:08X} - 0x{end:08X} ({(end-start)//1024}KB)")
    print("-" * 60)

    found = []
    addr = start

    while addr < end:
        # Read chunk with overlap for boundary matches
        read_size = min(chunk_size, end - addr)
        data = client.read_memory(addr, read_size)

        if data is None:
            print(f"  [!] Read failed at 0x{addr:08X}, skipping...")
            addr += chunk_size
            time.sleep(0.2)
            continue

        # Search for pattern in chunk
        offset = 0
        while True:
            pos = data.find(search_bytes, offset)
            if pos == -1:
                break

            found_addr = addr + pos
            print(f"  [FOUND] 0x{found_addr:08X}")

            # Show context
            context_start = max(0, pos - 16)
            context_end = min(len(data), pos + len(search_bytes) + 32)
            context = data[context_start:context_end]

            # Hex dump of context
            for i in range(0, len(context), 16):
                chunk = context[i:i+16]
                hex_str = ' '.join(f'{b:02X}' for b in chunk)
                ascii_str = ''.join(chr(b) if 32 <= b < 127 else '.' for b in chunk)
                line_addr = addr + context_start + i
                print(f"    {line_addr:08X}: {hex_str:<48} {ascii_str}")

            found.append(found_addr)
            offset = pos + 1

        addr += chunk_size - len(search_bytes)  # Overlap to catch boundary matches
        time.sleep(0.05)  # Rate limit

    return found


def main():
    parser = argparse.ArgumentParser(description="Find player name in memory")
    parser.add_argument("--host", "-H", default="127.0.0.1")
    parser.add_argument("--port", "-p", type=int, default=731)
    parser.add_argument("--name", "-n", default="Default", help="Player name to search for")
    args = parser.parse_args()

    print("=" * 60)
    print(f" Searching for player: {args.name}")
    print("=" * 60)

    client = XBDMClient(args.host, args.port, read_delay=0.05)

    if not client.connect():
        print("ERROR: Failed to connect")
        sys.exit(1)

    print("Connected!\n")

    # Search regions - focus on areas likely to have player data
    # PCR works at 0x55CAF0, so search around there and in low memory
    regions = [
        # Near PCR stats
        (0x550000, 0x580000, "Near PCR region"),

        # Profile data area
        (0x530000, 0x550000, "Profile region"),

        # Low memory where XBE data might be
        (0x010000, 0x100000, "Low memory (XBE data)"),

        # Extended search if not found
        (0x100000, 0x200000, "Extended low"),
        (0x200000, 0x400000, "Mid memory"),
    ]

    all_found = []

    for start, end, name in regions:
        print(f"\n{'='*60}")
        print(f" {name}")
        print('='*60)

        try:
            found = search_for_string(client, args.name, start, end)
            all_found.extend(found)

            if found:
                print(f"\n  Found {len(found)} match(es) in this region!")

        except KeyboardInterrupt:
            print("\n[Interrupted]")
            break
        except Exception as e:
            print(f"  Error: {e}")

    # Summary
    print("\n" + "=" * 60)
    print(" SUMMARY")
    print("=" * 60)

    if all_found:
        print(f"\nFound '{args.name}' at {len(all_found)} location(s):")
        for addr in all_found:
            print(f"  0x{addr:08X}")

        print("\nThese addresses likely contain session/player data structures.")
        print("The stats data should be nearby!")
    else:
        print(f"\nPlayer name '{args.name}' not found in searched regions.")
        print("Try searching more memory or check if player is in game.")

    client.disconnect()


if __name__ == "__main__":
    main()
