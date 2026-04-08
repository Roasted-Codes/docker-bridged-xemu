#!/usr/bin/env python3
"""Full-memory gametype scanner — find the real gametype address.

Three scanning modes:

1. DIRECT READ: Try reading the HaloCaster variant_info gametype byte
   at physical address 0x0360912C (variant_info + 0x40) via QMP.
   Also tries gva2gpa translation for the kernel VA.

2. SNAPSHOT: Dump memory regions to disk for later diffing.
   Take a snapshot during/after one gametype, then another gametype,
   then diff to find which addresses changed to the expected values.

3. SEARCH: Scan all memory for a specific gametype byte value,
   then cross-reference across multiple game states.

Usage:
    # Quick check — read variant_info gametype byte directly
    python research/memscan_gametype.py --direct

    # Take a memory snapshot (saves to research/snapshots/)
    python research/memscan_gametype.py --snapshot slayer

    # Diff two snapshots to find gametype address
    python research/memscan_gametype.py --diff slayer ctf

    # Search all accessible memory for a specific gametype value
    python research/memscan_gametype.py --search 2

    # Full physical RAM dump via pmemsave (fast, writes to host filesystem)
    python research/memscan_gametype.py --pmemsave /tmp/xbox_slayer.bin
"""

import argparse
import json
import os
import struct
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from qmp_client import QMPClient

SNAPSHOT_DIR = os.path.join(os.path.dirname(__file__), "snapshots")

GAMETYPE_ENUM = {
    0: "None", 1: "CTF", 2: "Slayer", 3: "Oddball", 4: "KOTH",
    5: "unused_5", 6: "unused_6",
    7: "Juggernaut", 8: "Territories", 9: "Assault",
}
NAME_TO_ID = {v.lower(): k for k, v in GAMETYPE_ENUM.items()
              if k not in (0, 5, 6)}

# Physical address ranges to scan
# Range 1: User-space .data section (where PGCR/PCR live)
DATA_SECTION = (0x46D6E0, 0x573858)  # .data VA range = physical range for user-space

# Range 2: HaloCaster kernel-mapped area (physical addresses ~50-60MB)
# This is where variant_info, game_stats, etc. live
HALOC_REGION = (0x3500000, 0x3700000)  # ~2MB region around HaloCaster offsets

# Known candidate addresses
CANDIDATES = {
    "variant_info_gametype": {
        "desc": "HaloCaster variant_info + 0x40 (single byte)",
        "physical": 0x036090EC + 0x40,  # 0x0360912C
        "kernel_va": 0x836090EC + 0x40,  # 0x8360912C
        "read_as": "byte",
    },
    "variant_info_base": {
        "desc": "HaloCaster variant_info struct (305 bytes)",
        "physical": 0x036090EC,
        "kernel_va": 0x836090EC,
        "read_as": "struct",
    },
    "pgcr_header_gametype": {
        "desc": "PGCR Display header + 0x84 (int32)",
        "user_va": 0x56B984,
        "read_as": "int32",
    },
    "gametype_profile": {
        "desc": "Discovered profile area + 0x04 (int32)",
        "user_va": 0x53D004,
        "read_as": "int32",
    },
    "xbox7887_gametype": {
        "desc": "xbox7887 gametype (int32, always 0 on docker-xemu)",
        "user_va": 0x50224C,
        "read_as": "int32",
    },
    "game_results_globals": {
        "desc": "HaloCaster game_results_globals (may contain gametype)",
        "physical": 0x5C000 + 0x35ACFB0,
        "kernel_va": 0x8005C000 + 0x35ACFB0,
        "read_as": "region_64",
    },
    "game_engine_globals": {
        "desc": "HaloCaster game_engine_globals (may contain gametype)",
        "physical": 0x5C000 + 0x35A53B8,
        "kernel_va": 0x8005C000 + 0x35A53B8,
        "read_as": "region_64",
    },
    "gametype_confirmed": {
        "desc": "Discovered via 4-way memscan diff (int32)",
        "user_va": 0x52ED24,
        "read_as": "int32",
    },
    "gametype_backup1": {
        "desc": "Backup 1 — failed KOTH (int32)",
        "user_va": 0x549634,
        "read_as": "int32",
    },
    "gametype_backup2": {
        "desc": "Backup 2 — failed KOTH (int32)",
        "user_va": 0x5614D4,
        "read_as": "int32",
    },
}


def read_physical(client, addr, length):
    """Read guest physical memory via QMP xp."""
    return client._read_physical(addr, length)


def read_via_gva2gpa(client, kernel_va, length):
    """Translate kernel VA via gva2gpa then read physical."""
    physical = client.translate_va(kernel_va)
    if physical is None:
        return None, None
    return client._read_physical(physical, length), physical


def fmt_gametype(value, as_byte=False):
    """Format a gametype value."""
    if value is None:
        return "READ FAIL"
    name = GAMETYPE_ENUM.get(value, f"unknown({value})")
    return f"{value} -> {name}"


def direct_read(client):
    """Try reading all known gametype candidate addresses."""
    print(f"\n{'='*70}")
    print(f"  DIRECT GAMETYPE ADDRESS READS")
    print(f"{'='*70}\n")

    for key, info in CANDIDATES.items():
        desc = info["desc"]
        read_as = info["read_as"]

        if "physical" in info:
            phys_addr = info["physical"]
            kernel_va = info.get("kernel_va")

            # Method 1: Direct physical read (strip high bit)
            if read_as == "byte":
                data = read_physical(client, phys_addr, 1)
                if data and len(data) >= 1:
                    val = data[0]
                    print(f"  {key:<30s} phys 0x{phys_addr:08X}:  byte={fmt_gametype(val)}")
                else:
                    print(f"  {key:<30s} phys 0x{phys_addr:08X}:  READ FAIL")

            elif read_as == "int32":
                data = read_physical(client, phys_addr, 4)
                if data and len(data) >= 4:
                    val = struct.unpack('<I', data)[0]
                    print(f"  {key:<30s} phys 0x{phys_addr:08X}:  int32={fmt_gametype(val)}")
                else:
                    print(f"  {key:<30s} phys 0x{phys_addr:08X}:  READ FAIL")

            elif read_as == "struct":
                data = read_physical(client, phys_addr, 0x131)
                if data and len(data) >= 0x131:
                    # Parse variant name (UTF-16LE, 16 chars)
                    try:
                        name = data[0:32].decode('utf-16-le').rstrip('\x00')
                    except:
                        name = ""
                    gt_byte = data[0x40]
                    # Parse scenario path
                    try:
                        scenario = data[0x130:0x230].split(b'\x00')[0].decode('ascii') if len(data) >= 0x230 else ""
                    except:
                        scenario = ""
                    non_zero = sum(1 for b in data if b != 0)
                    print(f"  {key:<30s} phys 0x{phys_addr:08X}:")
                    print(f"    Non-zero bytes: {non_zero}/{len(data)}")
                    print(f"    Variant name:   \"{name}\"")
                    print(f"    Gametype byte:  {fmt_gametype(gt_byte)}")
                    print(f"    Scenario:       \"{scenario}\"")
                else:
                    print(f"  {key:<30s} phys 0x{phys_addr:08X}:  READ FAIL (got {len(data) if data else 0} bytes)")

            elif read_as == "region_64":
                data = read_physical(client, phys_addr, 64)
                if data and len(data) >= 64:
                    non_zero = sum(1 for b in data if b != 0)
                    # Check first 16 int32s for gametype values
                    hits = []
                    for off in range(0, 64, 4):
                        val = struct.unpack_from('<I', data, off)[0]
                        if val in GAMETYPE_ENUM and 1 <= val <= 9:
                            hits.append((off, val))
                    # Also check bytes
                    for off in range(64):
                        val = data[off]
                        if val in GAMETYPE_ENUM and 1 <= val <= 9:
                            before = data[off-1] if off > 0 else 0
                            after = data[off+1] if off < 63 else 0
                            if before == 0 and after == 0 and (off, val) not in [(h[0], h[1]) for h in hits]:
                                hits.append((off, val))
                    print(f"  {key:<30s} phys 0x{phys_addr:08X}:  {non_zero}/64 non-zero", end="")
                    if hits:
                        print(f"  HITS: {', '.join(f'+0x{o:02X}={fmt_gametype(v)}' for o, v in hits)}")
                    else:
                        print()
                else:
                    print(f"  {key:<30s} phys 0x{phys_addr:08X}:  READ FAIL")

            # Method 2: gva2gpa translation (might give different physical addr)
            if kernel_va:
                data2, resolved_phys = read_via_gva2gpa(client, kernel_va, 4)
                if resolved_phys is not None:
                    expected_phys = kernel_va - 0x80000000
                    if resolved_phys != expected_phys:
                        print(f"    >>> gva2gpa 0x{kernel_va:08X} -> 0x{resolved_phys:08X}"
                              f" (NOT 0x{expected_phys:08X}!)")
                        # Re-read at the translated address
                        if read_as == "byte":
                            data3 = read_physical(client, resolved_phys, 1)
                            if data3:
                                print(f"    >>> Re-read at translated addr: byte={fmt_gametype(data3[0])}")
                        elif read_as in ("int32", "struct"):
                            size = 4 if read_as == "int32" else 0x131
                            data3 = read_physical(client, resolved_phys, size)
                            if data3 and read_as == "int32":
                                val = struct.unpack('<I', data3[:4])[0]
                                print(f"    >>> Re-read at translated addr: int32={fmt_gametype(val)}")
                            elif data3 and read_as == "struct":
                                gt_byte = data3[0x40] if len(data3) > 0x40 else None
                                print(f"    >>> Re-read at translated addr: gametype byte={fmt_gametype(gt_byte)}")
                    else:
                        print(f"    gva2gpa confirms: 0x{kernel_va:08X} -> 0x{resolved_phys:08X} (identity-mapped)")
                else:
                    print(f"    gva2gpa 0x{kernel_va:08X}: UNMAPPED (page not committed)")

        elif "user_va" in info:
            user_va = info["user_va"]
            # Translate user VA via gva2gpa
            data, phys = read_via_gva2gpa(client, user_va, 4)
            if data and len(data) >= 4:
                val = struct.unpack('<I', data)[0]
                phys_str = f" (phys 0x{phys:08X})" if phys else ""
                print(f"  {key:<30s} VA 0x{user_va:08X}{phys_str}:  int32={fmt_gametype(val)}")
            else:
                print(f"  {key:<30s} VA 0x{user_va:08X}:  READ FAIL")

    # Expanded context reads using xbe_map_index knowledge
    print(f"\n{'='*70}")
    print(f"  CONTEXT DUMPS (xbe_map_index guided)")
    print(f"{'='*70}\n")

    # 1. Game engine globals — read 256 bytes, look for gametype fields
    ge_phys = 0x5C000 + 0x35A53B8  # game_engine_globals physical
    data = read_physical(client, ge_phys, 256)
    if data and len(data) >= 256:
        print(f"  game_engine_globals (phys 0x{ge_phys:08X}, 256 bytes):")
        non_zero = sum(1 for b in data if b != 0)
        print(f"    Non-zero: {non_zero}/256")
        # Check every int32 for gametype values
        for off in range(0, 256, 4):
            val = struct.unpack_from('<I', data, off)[0]
            if 1 <= val <= 9 and val in GAMETYPE_ENUM:
                print(f"    +0x{off:02X}: int32 = {fmt_gametype(val)}")
        # Hex dump first 128 bytes
        for i in range(0, min(128, len(data)), 16):
            chunk = data[i:i+16]
            hex_part = " ".join(f"{b:02X}" for b in chunk)
            print(f"    {ge_phys + i:08X}  {hex_part}")

    # 2. Context around discovered gametype addresses (32 bytes each side)
    context_addrs = [
        ("gametype_confirmed", 0x52ED24),
        ("gametype_backup1",   0x549634),
        ("gametype_backup2",   0x5614D4),
    ]
    for label, va in context_addrs:
        start_va = va - 32
        data, phys = read_via_gva2gpa(client, start_va, 68)  # 32 before + 4 target + 32 after
        if data and len(data) >= 68:
            target_val = struct.unpack_from('<I', data, 32)[0]
            print(f"\n  {label} context (VA 0x{va:08X} = {fmt_gametype(target_val)}):")
            for i in range(0, len(data), 16):
                chunk = data[i:i+16]
                hex_part = " ".join(f"{b:02X}" for b in chunk)
                row_va = start_va + i
                marker = " <-- TARGET" if i <= 32 < i + 16 else ""
                print(f"    {row_va:08X}  {hex_part}{marker}")

    # 3. PGCR header — full 0x90 bytes, check ALL int32s
    header_data = client.read_memory_va(0x56B900, 0x90)
    if header_data and len(header_data) >= 0x90:
        print(f"\n  PGCR Header (VA 0x56B900, 0x90 bytes) — ALL int32 values:")
        for off in range(0, 0x90, 4):
            val = struct.unpack_from('<I', header_data, off)[0]
            if val != 0:
                gt_str = f" -> {GAMETYPE_ENUM[val]}" if val in GAMETYPE_ENUM else ""
                print(f"    +0x{off:02X}: 0x{val:08X} ({val}){gt_str}")

    print()


def take_snapshot(client, label):
    """Dump memory regions to disk for later diffing."""
    os.makedirs(SNAPSHOT_DIR, exist_ok=True)

    print(f"\nTaking memory snapshot '{label}'...")

    # Region 1: .data section (user-space, needs gva2gpa)
    data_start, data_end = DATA_SECTION
    data_size = data_end - data_start

    print(f"  Reading .data section: VA 0x{data_start:08X} - 0x{data_end:08X} ({data_size} bytes)...")

    # Translate the start VA to physical
    phys_start = client.translate_va(data_start)
    if phys_start is None:
        print(f"  ERROR: Cannot translate .data start VA 0x{data_start:08X}")
        return

    # Read in chunks (QMP xp is limited)
    CHUNK = 4096
    data_section = bytearray()
    addr = phys_start
    total = data_size
    read_so_far = 0

    while read_so_far < total:
        chunk_size = min(CHUNK, total - read_so_far)
        chunk = client._read_physical(addr, chunk_size)
        if chunk is None:
            print(f"\n  ERROR: Read failed at physical 0x{addr:08X}")
            break
        data_section.extend(chunk)
        addr += chunk_size
        read_so_far += chunk_size
        pct = read_so_far * 100 // total
        print(f"\r  .data section: {read_so_far}/{total} bytes ({pct}%)", end="", flush=True)

    print()

    # Region 2: HaloCaster kernel region (physical addresses directly)
    haloc_start, haloc_end = HALOC_REGION
    haloc_size = haloc_end - haloc_start

    print(f"  Reading HaloCaster region: phys 0x{haloc_start:08X} - 0x{haloc_end:08X} ({haloc_size} bytes)...")

    haloc_data = bytearray()
    addr = haloc_start
    total = haloc_size
    read_so_far = 0

    while read_so_far < total:
        chunk_size = min(CHUNK, total - read_so_far)
        chunk = client._read_physical(addr, chunk_size)
        if chunk is None:
            # Fill with zeros for unreadable regions
            haloc_data.extend(b'\x00' * chunk_size)
        else:
            haloc_data.extend(chunk)
        addr += chunk_size
        read_so_far += chunk_size
        pct = read_so_far * 100 // total
        print(f"\r  HaloCaster region: {read_so_far}/{total} bytes ({pct}%)", end="", flush=True)

    print()

    # Save snapshot
    snapshot = {
        "label": label,
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "regions": {
            "data_section": {
                "phys_start": phys_start,
                "va_start": data_start,
                "size": len(data_section),
            },
            "haloc_region": {
                "phys_start": haloc_start,
                "size": len(haloc_data),
            },
        },
    }

    # Write binary data
    data_path = os.path.join(SNAPSHOT_DIR, f"{label}_data.bin")
    haloc_path = os.path.join(SNAPSHOT_DIR, f"{label}_haloc.bin")
    meta_path = os.path.join(SNAPSHOT_DIR, f"{label}_meta.json")

    with open(data_path, 'wb') as f:
        f.write(data_section)
    with open(haloc_path, 'wb') as f:
        f.write(haloc_data)
    with open(meta_path, 'w') as f:
        json.dump(snapshot, f, indent=2)

    print(f"\n  Saved: {data_path} ({len(data_section)} bytes)")
    print(f"  Saved: {haloc_path} ({len(haloc_data)} bytes)")
    print(f"  Saved: {meta_path}")


def diff_snapshots(label_a, label_b):
    """Diff two snapshots and find gametype-related changes."""
    # Load metadata
    meta_a_path = os.path.join(SNAPSHOT_DIR, f"{label_a}_meta.json")
    meta_b_path = os.path.join(SNAPSHOT_DIR, f"{label_b}_meta.json")

    if not os.path.exists(meta_a_path) or not os.path.exists(meta_b_path):
        print(f"ERROR: Snapshot not found. Available snapshots:")
        for f in sorted(os.listdir(SNAPSHOT_DIR)):
            if f.endswith("_meta.json"):
                print(f"  {f.replace('_meta.json', '')}")
        return

    with open(meta_a_path) as f:
        meta_a = json.load(f)
    with open(meta_b_path) as f:
        meta_b = json.load(f)

    gt_a = NAME_TO_ID.get(label_a.lower(), None)
    gt_b = NAME_TO_ID.get(label_b.lower(), None)

    print(f"\n{'='*70}")
    print(f"  MEMORY DIFF: {label_a} vs {label_b}")
    if gt_a is not None and gt_b is not None:
        print(f"  Looking for: byte {gt_a} ({label_a}) -> {gt_b} ({label_b})")
    print(f"{'='*70}\n")

    # Diff each region
    for region_name in ["data_section", "haloc_region"]:
        suffix = "data" if region_name == "data_section" else "haloc"
        path_a = os.path.join(SNAPSHOT_DIR, f"{label_a}_{suffix}.bin")
        path_b = os.path.join(SNAPSHOT_DIR, f"{label_b}_{suffix}.bin")

        if not os.path.exists(path_a) or not os.path.exists(path_b):
            print(f"  {region_name}: Missing data file, skipping")
            continue

        with open(path_a, 'rb') as f:
            data_a = f.read()
        with open(path_b, 'rb') as f:
            data_b = f.read()

        min_len = min(len(data_a), len(data_b))
        region_info = meta_a["regions"][region_name]
        phys_base = region_info["phys_start"]
        va_base = region_info.get("va_start")

        # Find all changed bytes
        changes = []
        for i in range(min_len):
            if data_a[i] != data_b[i]:
                changes.append((i, data_a[i], data_b[i]))

        total_changes = len(changes)
        print(f"  {region_name}: {total_changes} bytes changed out of {min_len}")

        if total_changes == 0:
            continue

        # Filter for gametype-related changes
        gametype_hits = []
        for offset, val_a, val_b in changes:
            phys_addr = phys_base + offset
            va_addr = va_base + offset if va_base else None

            is_hit = False
            reason = ""

            # Check if the change matches expected gametype transition
            if gt_a is not None and gt_b is not None:
                if val_a == gt_a and val_b == gt_b:
                    is_hit = True
                    reason = f"EXACT MATCH: {val_a}({GAMETYPE_ENUM.get(val_a,'?')}) -> {val_b}({GAMETYPE_ENUM.get(val_b,'?')})"

            # Also check if either value is a valid gametype
            if not is_hit:
                if val_a in GAMETYPE_ENUM and 1 <= val_a <= 9 and val_b in GAMETYPE_ENUM and 1 <= val_b <= 9:
                    is_hit = True
                    reason = f"GAMETYPE CHANGE: {val_a}({GAMETYPE_ENUM.get(val_a,'?')}) -> {val_b}({GAMETYPE_ENUM.get(val_b,'?')})"

            if is_hit:
                gametype_hits.append((offset, phys_addr, va_addr, val_a, val_b, reason))

        if gametype_hits:
            print(f"\n  >>> GAMETYPE CANDIDATE ADDRESSES ({len(gametype_hits)} hits):")
            for offset, phys, va, a, b, reason in gametype_hits:
                va_str = f" (VA 0x{va:08X})" if va else ""
                print(f"    phys 0x{phys:08X}{va_str}: {a:3d} -> {b:3d}  {reason}")

                # Check surrounding context
                context_start = max(0, offset - 8)
                context_end = min(min_len, offset + 12)
                ctx_a = data_a[context_start:context_end]
                ctx_b = data_b[context_start:context_end]
                hex_a = ' '.join(f'{b:02X}' for b in ctx_a)
                hex_b = ' '.join(f'{b:02X}' for b in ctx_b)
                rel_pos = offset - context_start
                pointer = ' ' * (rel_pos * 3) + '^^'
                print(f"      before: {hex_a}")
                print(f"      after:  {hex_b}")
                print(f"              {pointer}")
        else:
            print(f"  No gametype-value changes found in {region_name}")

        # Also check for int32 gametype changes
        int32_hits = []
        for i in range(0, min_len - 3, 4):
            val_a_32 = struct.unpack_from('<I', data_a, i)[0]
            val_b_32 = struct.unpack_from('<I', data_b, i)[0]
            if val_a_32 != val_b_32:
                if gt_a is not None and gt_b is not None:
                    if val_a_32 == gt_a and val_b_32 == gt_b:
                        phys_addr = phys_base + i
                        va_addr = va_base + i if va_base else None
                        int32_hits.append((i, phys_addr, va_addr, val_a_32, val_b_32))

        if int32_hits:
            print(f"\n  >>> INT32 GAMETYPE MATCHES ({len(int32_hits)} hits):")
            for offset, phys, va, a, b in int32_hits:
                va_str = f" (VA 0x{va:08X})" if va else ""
                print(f"    phys 0x{phys:08X}{va_str}: int32 {a}({GAMETYPE_ENUM.get(a,'?')}) -> {b}({GAMETYPE_ENUM.get(b,'?')})")

    print()


def search_memory(client, target_value):
    """Search memory for a specific gametype value."""
    print(f"\n{'='*70}")
    print(f"  SEARCHING FOR GAMETYPE VALUE: {target_value} ({GAMETYPE_ENUM.get(target_value, '?')})")
    print(f"{'='*70}\n")

    CHUNK = 4096

    # Search .data section via user-space VA translation
    data_start, data_end = DATA_SECTION
    data_size = data_end - data_start

    print(f"  Scanning .data section (VA 0x{data_start:08X} - 0x{data_end:08X})...")

    phys_start = client.translate_va(data_start)
    if phys_start is None:
        print(f"  ERROR: Cannot translate VA 0x{data_start:08X}")
    else:
        byte_hits = []
        int32_hits = []
        addr = phys_start
        total = data_size
        scanned = 0

        while scanned < total:
            chunk_size = min(CHUNK, total - scanned)
            data = client._read_physical(addr, chunk_size)
            if data is None:
                addr += chunk_size
                scanned += chunk_size
                continue

            # Search for byte matches (isolated — surrounded by zeros)
            for i in range(len(data)):
                if data[i] == target_value:
                    before = data[i-1] if i > 0 else 0
                    after = data[i+1] if i < len(data)-1 else 0
                    if before == 0 and after == 0:
                        phys_addr = addr + i
                        va_addr = data_start + scanned + i
                        byte_hits.append((phys_addr, va_addr))

            # Search for int32 matches
            for i in range(0, len(data) - 3, 4):
                val = struct.unpack_from('<I', data, i)[0]
                if val == target_value:
                    phys_addr = addr + i
                    va_addr = data_start + scanned + i
                    int32_hits.append((phys_addr, va_addr))

            addr += chunk_size
            scanned += chunk_size
            pct = scanned * 100 // total
            print(f"\r  .data section: {scanned}/{total} bytes ({pct}%)", end="", flush=True)

        print()
        print(f"  Isolated byte matches: {len(byte_hits)}")
        for phys, va in byte_hits[:30]:
            print(f"    phys 0x{phys:08X} (VA 0x{va:08X})")
        if len(byte_hits) > 30:
            print(f"    ... and {len(byte_hits) - 30} more")

        print(f"  Int32 matches: {len(int32_hits)}")
        for phys, va in int32_hits[:30]:
            print(f"    phys 0x{phys:08X} (VA 0x{va:08X})")
        if len(int32_hits) > 30:
            print(f"    ... and {len(int32_hits) - 30} more")

    # Search HaloCaster region (physical addresses directly)
    haloc_start, haloc_end = HALOC_REGION
    haloc_size = haloc_end - haloc_start

    print(f"\n  Scanning HaloCaster region (phys 0x{haloc_start:08X} - 0x{haloc_end:08X})...")

    byte_hits = []
    int32_hits = []
    addr = haloc_start
    total = haloc_size
    scanned = 0

    while scanned < total:
        chunk_size = min(CHUNK, total - scanned)
        data = client._read_physical(addr, chunk_size)
        if data is None:
            addr += chunk_size
            scanned += chunk_size
            continue

        for i in range(len(data)):
            if data[i] == target_value:
                before = data[i-1] if i > 0 else 0
                after = data[i+1] if i < len(data)-1 else 0
                if before == 0 and after == 0:
                    phys_addr = addr + i
                    byte_hits.append(phys_addr)

        for i in range(0, len(data) - 3, 4):
            val = struct.unpack_from('<I', data, i)[0]
            if val == target_value:
                phys_addr = addr + i
                int32_hits.append(phys_addr)

        addr += chunk_size
        scanned += chunk_size
        pct = scanned * 100 // total
        print(f"\r  HaloCaster region: {scanned}/{total} bytes ({pct}%)", end="", flush=True)

    print()
    print(f"  Isolated byte matches: {len(byte_hits)}")
    for phys in byte_hits[:30]:
        kernel_va = phys + 0x80000000
        print(f"    phys 0x{phys:08X} (kernel VA 0x{kernel_va:08X})")
    if len(byte_hits) > 30:
        print(f"    ... and {len(byte_hits) - 30} more")

    print(f"  Int32 matches: {len(int32_hits)}")
    for phys in int32_hits[:30]:
        kernel_va = phys + 0x80000000
        print(f"    phys 0x{phys:08X} (kernel VA 0x{kernel_va:08X})")
    if len(int32_hits) > 30:
        print(f"    ... and {len(int32_hits) - 30} more")

    print()


def pmemsave(client, filepath):
    """Dump full 64MB guest physical RAM to host file via QMP pmemsave."""
    print(f"\nDumping 64MB Xbox RAM to: {filepath}")
    print(f"(File is written on the HOST running xemu, not this machine)")

    cmd = {
        "execute": "human-monitor-command",
        "arguments": {
            "command-line": f'pmemsave 0 0x4000000 "{filepath}"'
        }
    }
    response = client._send_command(cmd)
    if response and 'return' in response:
        print(f"  pmemsave command sent successfully.")
        print(f"  Check {filepath} on the xemu host ({client.host}).")
        print(f"\n  To diff two dumps:")
        print(f"    python research/memscan_gametype.py --diff-raw {filepath} <other_dump>")
    else:
        print(f"  ERROR: pmemsave failed. Response: {response}")


def diff_raw_dumps(path_a, path_b, label_a="A", label_b="B"):
    """Diff two raw 64MB memory dumps."""
    print(f"\nDiffing raw memory dumps:")
    print(f"  A: {path_a}")
    print(f"  B: {path_b}")

    with open(path_a, 'rb') as f:
        data_a = f.read()
    with open(path_b, 'rb') as f:
        data_b = f.read()

    min_len = min(len(data_a), len(data_b))
    print(f"  Size A: {len(data_a)} bytes, Size B: {len(data_b)} bytes")
    print(f"  Comparing {min_len} bytes...\n")

    # Find all differences
    total_diffs = 0
    gametype_byte_hits = []
    gametype_int32_hits = []

    for i in range(min_len):
        if data_a[i] != data_b[i]:
            total_diffs += 1
            a, b = data_a[i], data_b[i]
            # Check for gametype byte transitions
            if a in GAMETYPE_ENUM and 1 <= a <= 9 and b in GAMETYPE_ENUM and 1 <= b <= 9:
                before_a = data_a[i-1] if i > 0 else 0
                after_a = data_a[i+1] if i < min_len-1 else 0
                before_b = data_b[i-1] if i > 0 else 0
                after_b = data_b[i+1] if i < min_len-1 else 0
                # Prefer isolated values
                isolated = (before_a == 0 or before_a == before_b) and (after_a == 0 or after_a == after_b)
                gametype_byte_hits.append((i, a, b, isolated))

    # Int32 gametype transitions
    for i in range(0, min_len - 3, 4):
        a32 = struct.unpack_from('<I', data_a, i)[0]
        b32 = struct.unpack_from('<I', data_b, i)[0]
        if a32 != b32 and a32 in GAMETYPE_ENUM and 1 <= a32 <= 9 and b32 in GAMETYPE_ENUM and 1 <= b32 <= 9:
            gametype_int32_hits.append((i, a32, b32))

    print(f"  Total bytes changed: {total_diffs}")
    print(f"  Gametype byte transitions: {len(gametype_byte_hits)}")
    print(f"  Gametype int32 transitions: {len(gametype_int32_hits)}")

    if gametype_byte_hits:
        print(f"\n  >>> BYTE-LEVEL GAMETYPE CANDIDATES:")
        # Show isolated hits first
        isolated = [(i, a, b) for i, a, b, iso in gametype_byte_hits if iso]
        non_isolated = [(i, a, b) for i, a, b, iso in gametype_byte_hits if not iso]

        if isolated:
            print(f"  Isolated (high confidence):")
            for addr, a, b in isolated[:50]:
                region = "user-space" if addr < 0x600000 else "kernel-mapped" if addr >= 0x3000000 else "other"
                print(f"    phys 0x{addr:08X}: {a}({GAMETYPE_ENUM.get(a,'?')}) -> {b}({GAMETYPE_ENUM.get(b,'?')})  [{region}]")

        if non_isolated:
            print(f"  Non-isolated ({len(non_isolated)} hits, showing first 20):")
            for addr, a, b in non_isolated[:20]:
                print(f"    phys 0x{addr:08X}: {a}({GAMETYPE_ENUM.get(a,'?')}) -> {b}({GAMETYPE_ENUM.get(b,'?')})")

    if gametype_int32_hits:
        print(f"\n  >>> INT32 GAMETYPE CANDIDATES:")
        for addr, a, b in gametype_int32_hits[:50]:
            region = "user-space" if addr < 0x600000 else "kernel-mapped" if addr >= 0x3000000 else "other"
            print(f"    phys 0x{addr:08X}: {a}({GAMETYPE_ENUM.get(a,'?')}) -> {b}({GAMETYPE_ENUM.get(b,'?')})  [{region}]")

    print()


def main():
    parser = argparse.ArgumentParser(
        description="Full-memory gametype scanner",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--host", default="172.20.0.10")
    parser.add_argument("--qmp", type=int, default=4444, help="QMP port (default: 4444)")

    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--direct", action="store_true",
                       help="Read all known gametype candidate addresses")
    group.add_argument("--snapshot", type=str, metavar="LABEL",
                       help="Take memory snapshot (use gametype name as label)")
    group.add_argument("--diff", nargs=2, metavar=("LABEL_A", "LABEL_B"),
                       help="Diff two snapshots")
    group.add_argument("--search", type=int, metavar="VALUE",
                       help="Search memory for gametype value (1-9)")
    group.add_argument("--pmemsave", type=str, metavar="FILEPATH",
                       help="Dump 64MB RAM to host file via pmemsave")
    group.add_argument("--diff-raw", nargs=2, metavar=("FILE_A", "FILE_B"),
                       help="Diff two raw memory dump files")

    args = parser.parse_args()

    # Offline operations (no QMP needed)
    if args.diff:
        diff_snapshots(args.diff[0], args.diff[1])
        return

    if args.diff_raw:
        diff_raw_dumps(args.diff_raw[0], args.diff_raw[1])
        return

    # Online operations (need QMP)
    client = QMPClient(args.host, args.qmp, timeout=15.0)
    if not client.connect():
        print(f"QMP connection failed ({args.host}:{args.qmp})")
        sys.exit(1)

    try:
        if args.direct:
            direct_read(client)
        elif args.snapshot:
            take_snapshot(client, args.snapshot)
        elif args.search is not None:
            search_memory(client, args.search)
        elif args.pmemsave:
            pmemsave(client, args.pmemsave)
    finally:
        client.disconnect()


if __name__ == "__main__":
    main()
