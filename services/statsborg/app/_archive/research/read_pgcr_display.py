#!/usr/bin/env python3
"""
Read PGCR Display Structure at 0x56B900.
Run this while on the post-game carnage report screen.
"""

import sys
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

import struct
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from xbdm_client import XBDMClient

PGCR_DISPLAY_BASE = 0x56B900

def read_pgcr_display(client):
    """Read and parse PGCR display structure."""
    data = client.read_memory(PGCR_DISPLAY_BASE, 0x200)
    if not data:
        print("ERROR: Failed to read PGCR display")
        return None
    
    # Parse known fields
    result = {
        # Standard PCR offsets (may be zeroed)
        "pcr_kills": struct.unpack('<i', data[0x60:0x64])[0],
        "pcr_deaths": struct.unpack('<i', data[0x64:0x68])[0],
        "pcr_assists": struct.unpack('<i', data[0x68:0x6C])[0],
        "pcr_suicides": struct.unpack('<i', data[0x6C:0x70])[0],
        
        # Place
        "place": struct.unpack('<i', data[0x84:0x88])[0],
        
        # Player name
        "name": data[0x90:0xB0].decode('utf-16-le', errors='replace').rstrip('\x00'),
        
        # Score string
        "score_string": data[0xCC:0xDC].decode('utf-16-le', errors='replace').rstrip('\x00'),
        
        # Verified stats
        "deaths": struct.unpack('<i', data[0xF4:0xF8])[0],
        "suicides": struct.unpack('<i', data[0xFC:0x100])[0],
        "total_shots": struct.unpack('<i', data[0x114:0x118])[0],
        "shots_hit": struct.unpack('<i', data[0x118:0x11C])[0],
        "headshots": struct.unpack('<i', data[0x11C:0x120])[0],
        
        # Killed-by array (first 4 slots)
        "killed_by_self": struct.unpack('<i', data[0x120:0x124])[0],
        "killed_by_p1": struct.unpack('<i', data[0x124:0x128])[0],
        "killed_by_p2": struct.unpack('<i', data[0x128:0x12C])[0],
        "killed_by_p3": struct.unpack('<i', data[0x12C:0x130])[0],
        
        # Place string
        "place_string": data[0x168:0x178].decode('utf-16-le', errors='replace').rstrip('\x00'),
    }
    
    # Also check for kills at various offsets
    result["possible_kills"] = {}
    for offset in [0xE8, 0xEC, 0xF0]:
        val = struct.unpack('<i', data[offset:offset+4])[0]
        if val != 0:
            result["possible_kills"][f"0x{offset:03X}"] = val
    
    return result

def main():
    client = XBDMClient('127.0.0.1', 731, read_delay=0.05)
    if not client.connect():
        print("ERROR: Failed to connect")
        sys.exit(1)
    
    print("=" * 60)
    print(" PGCR DISPLAY READER")
    print("=" * 60)
    
    stats = read_pgcr_display(client)
    if stats:
        print(f"\nPlayer: {stats['name']}")
        print(f"Place: {stats['place']} ({stats['place_string'].strip()})")
        print(f"Score: {stats['score_string'].strip()}")
        print()
        print("STATS:")
        print(f"  Deaths:      {stats['deaths']}")
        print(f"  Suicides:    {stats['suicides']}")
        print(f"  Total shots: {stats['total_shots']}")
        print(f"  Shots hit:   {stats['shots_hit']}")
        print(f"  Headshots:   {stats['headshots']}")
        print()
        print("KILLED-BY:")
        print(f"  By self:     {stats['killed_by_self']}")
        print(f"  By player 1: {stats['killed_by_p1']}")
        print(f"  By player 2: {stats['killed_by_p2']}")
        print(f"  By player 3: {stats['killed_by_p3']}")
        print()
        print("PCR-STYLE OFFSETS (0x60-0x6C):")
        print(f"  kills:    {stats['pcr_kills']}")
        print(f"  deaths:   {stats['pcr_deaths']}")
        print(f"  assists:  {stats['pcr_assists']}")
        print(f"  suicides: {stats['pcr_suicides']}")
        
        if stats["possible_kills"]:
            print()
            print("POSSIBLE KILLS LOCATIONS:")
            for off, val in stats["possible_kills"].items():
                print(f"  {off}: {val}")
    
    client.disconnect()

if __name__ == "__main__":
    main()
