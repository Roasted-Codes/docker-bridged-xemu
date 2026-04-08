"""
XBDM Memory Discovery - Find where Halo 2 game data lives in virtual memory.

Uses walkmem, modules, and modsections XBDM commands to enumerate the
memory layout without reading any actual data (so no freeze risk).

Usage: python discover_addresses.py [host]
"""
import sys
import time
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from xbdm_client import XBDMClient

HOST = sys.argv[1] if len(sys.argv) > 1 else "172.20.0.51"
PORT = 731

# HaloCaster offsets for reference
HALOC_OFFSETS = {
    "game_stats":       0x35ADF02,
    "session_players":  0x35AD344,
    "life_cycle":       0x35E4F04,
    "variant_info":     0x35AD0EC,
    "game_results":     0x35ACFB0,
    "weapon_stats":     0x35ADFE0,
    "medal_stats":      0x35ADF4E,
    "tags":             0x360558C,
}


def main():
    print(f"XBDM Memory Discovery on {HOST}:{PORT}")
    print("=" * 70)

    client = XBDMClient(HOST, PORT, timeout=5.0, read_delay=0.3)
    if not client.connect():
        print("Failed to connect to XBDM")
        return

    info = client.debug_info()
    print(f"Connected: {info}")

    # Step 1: List loaded modules
    print(f"\n{'='*70}")
    print("LOADED MODULES")
    print("=" * 70)
    modules = client.get_modules()
    if modules:
        for m in modules:
            print(f"  {m}")
    else:
        print("  (no modules returned or command not supported)")

    # Step 2: Try modsections for each module
    print(f"\n{'='*70}")
    print("MODULE SECTIONS")
    print("=" * 70)

    # Try common XBE module names
    module_names = ["default.xbe", "halo2.xbe", "default"]
    # Also extract names from modules output
    for m in modules:
        # Module lines often contain name="xxx"
        if 'name=' in m:
            parts = m.split('name=')
            if len(parts) > 1:
                name = parts[1].strip().strip('"').split()[0].strip('"')
                if name and name not in module_names:
                    module_names.insert(0, name)

    for name in module_names:
        time.sleep(0.3)
        print(f"\n  modsections name=\"{name}\":")
        sections = client.get_module_sections(name)
        if sections:
            for s in sections:
                base = s.get('base', '?')
                size = s.get('size', '?')
                sname = s.get('name', '?')
                flags = s.get('flags', '')
                base_str = f"0x{base:08X}" if isinstance(base, int) else str(base)
                size_str = f"0x{size:08X}" if isinstance(size, int) else str(size)
                if isinstance(base, int) and isinstance(size, int):
                    end = base + size
                    print(f"    {sname:16s}  {base_str} - 0x{end:08X}  size={size_str}  {flags}")
                else:
                    print(f"    {sname:16s}  base={base_str}  size={size_str}  {flags}")
            break  # Found a working module name
        else:
            print(f"    (not found or command not supported)")

    # Step 3: Walk committed memory
    print(f"\n{'='*70}")
    print("COMMITTED MEMORY REGIONS (walkmem)")
    print("=" * 70)
    time.sleep(0.3)
    regions = client.walk_memory()
    if regions:
        total_committed = 0
        for r in regions:
            base = r.get('base', r.get('addr', '?'))
            size = r.get('size', r.get('length', '?'))
            protect = r.get('protect', '')

            if isinstance(base, int) and isinstance(size, int):
                end = base + size
                total_committed += size
                # Highlight regions that could contain game data
                marker = ""
                if 0x50000 <= base <= 0x600000:
                    marker = "  <-- GAME DATA RANGE"
                elif base >= 0x80000000:
                    marker = "  <-- KERNEL"
                print(f"  0x{base:08X} - 0x{end:08X}  size=0x{size:06X} ({size:>8d})  protect={protect}{marker}")
            else:
                print(f"  base={base}  size={size}  protect={protect}")

        print(f"\n  Total committed: {total_committed:,} bytes ({total_committed/1024/1024:.1f} MB)")
        print(f"  Region count: {len(regions)}")
    else:
        print("  (no regions returned or command not supported)")

    # Step 4: If we got sections, compute addresses
    if sections:
        print(f"\n{'='*70}")
        print("COMPUTED HALOC ADDRESSES")
        print("=" * 70)

        # Find .data section
        data_section = None
        for s in sections:
            sname = s.get('name', '')
            if sname in ('.data', 'DATA', '.bss'):
                data_section = s
                break

        if data_section:
            data_base = data_section.get('base', 0)
            data_size = data_section.get('size', 0)
            print(f"  .data section: base=0x{data_base:08X}  size=0x{data_size:08X}")
            print()

            # The HaloCaster offsets are relative to XBE physical load base (0x5C000)
            # The .data section VA tells us where that maps in virtual memory
            # We need to figure out the relationship between haloc_offset and section offset
            for name, offset in sorted(HALOC_OFFSETS.items(), key=lambda x: x[1]):
                # Physical addr = 0x5C000 + offset
                phys = 0x5C000 + offset
                # Kernel VA (what we tried before, failed above ~48MB)
                kernel_va = 0x80000000 + phys
                print(f"  {name:30s}  haloc=0x{offset:08X}  phys=0x{phys:08X}  kernel_va=0x{kernel_va:08X}")
        else:
            print("  Could not find .data section")

    # Step 5: Quick sanity test — read a few bytes from known good address
    print(f"\n{'='*70}")
    print("SANITY CHECK")
    print("=" * 70)
    time.sleep(0.3)
    data = client.read_memory(0x53D008, 32)
    if data:
        nonzero = sum(1 for b in data if b != 0)
        preview = " ".join(f"{b:02x}" for b in data[:16])
        print(f"  0x53D008 (profile): OK ({nonzero} non-zero bytes)")
        print(f"    {preview}")
    else:
        print(f"  0x53D008 (profile): FAILED")

    client.disconnect()
    print(f"\n{'='*70}")
    print("Done.")


if __name__ == "__main__":
    main()
