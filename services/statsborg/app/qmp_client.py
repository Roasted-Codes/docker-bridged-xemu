"""
QMP Client — Read Xemu guest physical memory via QEMU Machine Protocol.

Provides the same read_memory(addr, size) interface as XBDMClient,
so it is a drop-in replacement for reading Xbox memory.

Two read modes:
  1. read_memory(addr, size)    — kernel VAs (0x80000000+), strips high bit
  2. read_memory_va(addr, size) — any Xbox VA, uses gva2gpa page table walk

Usage:
    # As a library
    from qmp_client import QMPClient
    client = QMPClient('localhost', 4444)
    client.connect()
    data = client.read_memory(0x83640F04, 4)      # kernel VA → physical read
    data = client.read_memory_va(0x56B990, 0x114)  # user VA → gva2gpa → physical

    # Standalone test (reads PGCR Display)
    python qmp_client.py [host] [port]

Requires Xemu launched with:
    -qmp tcp:0.0.0.0:4444,server,nowait
"""

import json
import re
import socket
import struct
import sys
from typing import Optional


class QMPClient:
    """
    QMP client for reading Xemu guest physical memory.

    Uses the 'xp' monitor command which reads by guest physical address,
    bypassing Xbox virtual memory entirely. This gives access to all 64MB
    of Xbox RAM including regions in the uncommitted kernel VA gap that
    XBDM cannot reach.
    """

    DEFAULT_HOST = 'localhost'
    DEFAULT_PORT = 4444

    def __init__(self, host: str = DEFAULT_HOST, port: int = DEFAULT_PORT,
                 timeout: float = 10.0):
        self.host = host
        self.port = port
        self.timeout = timeout
        self._sock: Optional[socket.socket] = None
        self._sockfile = None
        self._connected = False
        self._va_cache: dict = {}  # VA→PA cache (page tables change between games!)

    def connect(self) -> bool:
        """Connect to QMP and negotiate capabilities."""
        try:
            self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self._sock.settimeout(self.timeout)
            self._sock.connect((self.host, self.port))
            self._sockfile = self._sock.makefile('r')

            # Read QMP greeting
            greeting = self._json_read()
            if not greeting or 'QMP' not in greeting:
                print("ERROR: Invalid QMP greeting", file=sys.stderr)
                self.disconnect()
                return False

            # Negotiate capabilities
            resp = self._send_command({"execute": "qmp_capabilities"})
            if not resp or 'return' not in resp:
                print("ERROR: QMP capabilities negotiation failed", file=sys.stderr)
                self.disconnect()
                return False

            self._connected = True
            return True

        except (socket.error, socket.timeout, OSError) as e:
            print(f"ERROR: QMP connect failed: {e}", file=sys.stderr)
            self.disconnect()
            return False

    def connect_with_retry(self, max_retries: int = 0, backoff: float = 5.0,
                           max_backoff: float = 60.0) -> bool:
        """Connect to QMP with retry and exponential backoff.

        Args:
            max_retries: Max attempts (0 = retry forever until connected).
            backoff: Initial delay between retries in seconds.
            max_backoff: Maximum delay cap in seconds.

        Returns:
            True once connected, False if max_retries exhausted.
        """
        import time
        attempt = 0
        delay = backoff
        while True:
            attempt += 1
            if self.connect():
                return True
            if max_retries > 0 and attempt >= max_retries:
                return False
            print(f"[QMP] Retrying in {delay:.0f}s... (attempt {attempt})",
                  file=sys.stderr)
            # Sleep in short intervals so Ctrl+C is responsive
            elapsed = 0.0
            while elapsed < delay:
                time.sleep(min(0.5, delay - elapsed))
                elapsed += 0.5
            delay = min(delay * 2, max_backoff)

    def reconnect(self, max_retries: int = 0, backoff: float = 5.0,
                  max_backoff: float = 60.0) -> bool:
        """Disconnect, then reconnect with retry. See connect_with_retry()."""
        self.disconnect()
        return self.connect_with_retry(max_retries, backoff, max_backoff)

    def disconnect(self):
        """Close QMP connection."""
        self._connected = False
        self._va_cache.clear()
        if self._sockfile:
            try:
                self._sockfile.close()
            except Exception:
                pass
            self._sockfile = None
        if self._sock:
            try:
                self._sock.close()
            except Exception:
                pass
            self._sock = None

    def clear_va_cache(self):
        """Clear the VA→PA translation cache.

        MUST be called when detecting a new game — Xbox page tables change
        between games, remapping user-space VAs to different physical pages.
        """
        self._va_cache.clear()

    @property
    def is_connected(self) -> bool:
        return self._connected

    def _json_read(self) -> Optional[dict]:
        """Read one JSON response, skipping async event messages."""
        while True:
            line = self._sockfile.readline()
            if not line:
                return None
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            # Skip async events, return commands/greetings
            if 'event' in obj:
                continue
            return obj

    def _send_command(self, cmd: dict) -> Optional[dict]:
        """Send a JSON command and return the response."""
        if not self._sock:
            return None
        try:
            data = json.dumps(cmd).encode('utf-8')
            self._sock.sendall(data)
            return self._json_read()
        except (socket.error, socket.timeout, OSError) as e:
            print(f"ERROR: QMP command failed: {e}", file=sys.stderr)
            self._connected = False
            return None

    @staticmethod
    def _xbox_va_to_physical(addr: int) -> int:
        """Convert Xbox kernel VA to guest physical address.

        Kernel addresses (0x80000000+): physical = addr - 0x80000000
        User addresses (below 0x80000000): passed through as-is.
        Note: user-space VAs won't work with xp — use XBDM for those.
        """
        if addr >= 0x80000000:
            return addr - 0x80000000
        return addr

    def read_memory(self, address: int, length: int) -> Optional[bytes]:
        """
        Read Xbox memory via QMP. Drop-in replacement for XBDMClient.read_memory().

        Handles all address types automatically:
        - User-space VAs (< 0x80000000): translated via gva2gpa page table walk
        - Kernel-space VAs (>= 0x80000000): high bit stripped for physical address
        - Physical addresses: passed directly when called internally

        Args:
            address: Xbox virtual address (user or kernel) or physical address
            length: Number of bytes to read

        Returns:
            bytes if successful, None on error
        """
        if not self._connected:
            return None

        if address < 0x80000000:
            # User-space VA — must translate via page table walk
            return self.read_memory_va(address, length)

        # Kernel VA or physical — strip high bit if kernel
        physical = self._xbox_va_to_physical(address)
        return self._read_physical(physical, length)

    def _read_physical(self, physical: int, length: int) -> Optional[bytes]:
        """Read guest physical memory directly via xp command."""
        cmd = {
            "execute": "human-monitor-command",
            "arguments": {
                "command-line": f"xp /{length}xb 0x{physical:x}"
            }
        }

        response = self._send_command(cmd)
        if not response or 'return' not in response:
            return None

        return self._parse_xp_response(response['return'], length)

    def translate_va(self, va: int) -> Optional[int]:
        """Translate an Xbox guest virtual address to guest physical address.

        Uses QMP's gva2gpa command which performs a page table walk.
        Results are cached — Xbox page tables are stable at runtime.

        Args:
            va: Xbox virtual address

        Returns:
            Guest physical address, or None if unmapped
        """
        if not self._connected:
            return None

        # Cache lookup (page-aligned: VA page → PA page, then add offset)
        page_va = va & ~0xFFF
        if page_va in self._va_cache:
            return self._va_cache[page_va] + (va & 0xFFF)

        cmd = {
            "execute": "human-monitor-command",
            "arguments": {
                "command-line": f"gva2gpa 0x{va:x}"
            }
        }
        response = self._send_command(cmd)
        if not response or 'return' not in response:
            return None

        text = response['return']
        # Success: "gpa: 0x366b990\r\n"
        # Failure: "gva2gpa: unable to translate\r\n" or similar
        match = re.search(r'gpa:\s*0x([0-9a-fA-F]+)', text)
        if not match:
            return None

        physical = int(match.group(1), 16)
        # Cache the page-aligned mapping
        self._va_cache[page_va] = physical & ~0xFFF
        return physical

    def read_memory_va(self, va: int, length: int) -> Optional[bytes]:
        """Read guest memory by Xbox virtual address (any address space).

        Translates the VA to physical via gva2gpa page table walk,
        then reads physical memory with xp. Handles page boundary
        crossings by translating each page separately.

        Args:
            va: Xbox virtual address (user or kernel space)
            length: Number of bytes to read

        Returns:
            bytes if successful, None on error
        """
        if not self._connected or length <= 0:
            return None

        PAGE_SIZE = 0x1000
        result = bytearray()
        offset = 0

        while offset < length:
            current_va = va + offset
            page_offset = current_va & (PAGE_SIZE - 1)
            chunk_size = min(length - offset, PAGE_SIZE - page_offset)

            physical = self.translate_va(current_va)
            if physical is None:
                return None

            data = self._read_physical(physical, chunk_size)
            if data is None:
                return None

            result.extend(data)
            offset += chunk_size

        return bytes(result)

    def save_ram(self, filepath: str) -> bool:
        """Save full 64MB Xbox RAM to a file via pmemsave.

        Args:
            filepath: Destination file path (can be absolute or relative)

        Returns:
            True if command was sent successfully, False otherwise
        """
        if not self._connected:
            print("ERROR: Not connected to QMP", file=sys.stderr)
            return False

        cmd = {
            "execute": "pmemsave",
            "arguments": {
                "val": 0,                    # start address (physical)
                "size": 67108864,            # 64MB in bytes
                "filename": str(filepath)
            }
        }

        try:
            response = self._send_command(cmd)
            if response and "error" not in response:
                return True
            else:
                error = response.get("error", {}).get("desc", "unknown") if response else "no response"
                print(f"ERROR: pmemsave failed: {error}", file=sys.stderr)
                return False
        except Exception as e:
            print(f"ERROR: pmemsave exception: {e}", file=sys.stderr)
            return False

    @staticmethod
    def _parse_xp_response(text: str, expected_length: int) -> Optional[bytes]:
        """Parse QMP monitor hex output into bytes.

        xp output format:
            0000000003640f04: 0x03 0x00 0x00 0x00
            0000000003640f08: 0x01 0x02 0x03 0x04
        """
        hex_matches = re.findall(r'0x([0-9a-fA-F]{2})', text)
        if not hex_matches:
            return None
        result = bytes(int(h, 16) for h in hex_matches[:expected_length])
        if len(result) < expected_length:
            return None
        return result

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, *args):
        self.disconnect()


# =========================================================================
# Standalone test
# =========================================================================

def _is_valid_name(data: bytes) -> bool:
    """Check if raw UTF-16LE name bytes contain printable ASCII."""
    try:
        name = data.decode('utf-16-le').rstrip('\x00')
    except (UnicodeDecodeError, ValueError):
        return False
    return bool(name) and all(0x20 <= ord(c) <= 0x7E for c in name)


def _test_pgcr(client: QMPClient):
    """Read PGCR Display via QMP (same data XBDM reads at 0x56B900)."""
    from halo2_structs import (
        PCRPlayerStats, PCR_PLAYER_SIZE, TeamStats, GameType,
        PGCR_DISPLAY_HEADER, PGCR_DISPLAY_HEADER_SIZE,
        PGCR_DISPLAY_BASE, PGCR_DISPLAY_SIZE,
        PGCR_DISPLAY_GAMETYPE_ADDR,
        PGCR_DISPLAY_TEAM_BASE, TEAM_DATA_STRIDE, MAX_TEAMS,
        GAMETYPE_NAMES, decode_medals,
    )

    # Translate key addresses
    print("--- Address Translation (gva2gpa) ---")
    va_list = [
        ("PGCR Header", PGCR_DISPLAY_HEADER),
        ("Player 0", PGCR_DISPLAY_BASE),
        ("Team Data", PGCR_DISPLAY_TEAM_BASE),
    ]
    for label, va in va_list:
        phys = client.translate_va(va)
        if phys is not None:
            print(f"  {label}: VA 0x{va:08X} -> PA 0x{phys:08X}")
        else:
            print(f"  {label}: VA 0x{va:08X} -> UNMAPPED")
            print("\nERROR: Cannot translate PGCR addresses. Game may not be loaded.")
            return

    # Read gametype
    print("\n--- Gametype ---")
    data = client.read_memory_va(PGCR_DISPLAY_GAMETYPE_ADDR, 4)
    gametype = None
    if data:
        gt_val = struct.unpack('<I', data)[0]
        try:
            gametype = GameType(gt_val)
            print(f"  {gametype.name} ({gt_val})")
        except ValueError:
            print(f"  Unknown ({gt_val})")
    else:
        print("  Failed to read")

    # Read players
    print("\n--- PGCR Players (via QMP gva2gpa) ---")
    players = []
    for i in range(16):
        va = PGCR_DISPLAY_BASE + (i * PGCR_DISPLAY_SIZE)
        data = client.read_memory_va(va, PCR_PLAYER_SIZE)
        if not data or not _is_valid_name(data[0:32]):
            continue
        player = PCRPlayerStats.from_bytes(data)
        players.append(player)

    if not players:
        print("  No players found (PGCR may not be populated)")
    else:
        # Sort by place
        players.sort(key=lambda p: p.place)
        gt_name = gametype.name.lower() if gametype else "slayer"
        for p in players:
            medals = decode_medals(p.medals_earned_by_type)
            medal_str = f" | Medals: {', '.join(medals)}" if medals else ""
            gt_stats = p.get_gametype_stats(gt_name)
            gt_str = " | ".join(f"{k}: {v}" for k, v in gt_stats.items() if v)
            gt_str = f" | {gt_str}" if gt_str else ""
            acc = f"{p.shots_hit}/{p.total_shots}" if p.total_shots else "0/0"
            print(f"  {p.place_string or '?':>4s} {p.player_name:<16s} "
                  f"K:{p.kills} D:{p.deaths} A:{p.assists} S:{p.suicides} "
                  f"| Acc: {acc} HS:{p.headshots}{gt_str}{medal_str}")

    # Read teams
    print("\n--- Teams ---")
    teams = []
    for i in range(MAX_TEAMS):
        va = PGCR_DISPLAY_TEAM_BASE + (i * TEAM_DATA_STRIDE)
        data = client.read_memory_va(va, TEAM_DATA_STRIDE)
        if not data:
            continue
        team = TeamStats.from_bytes(data, index=i)
        if team.name.strip() and all(0x20 <= ord(c) <= 0x7E for c in team.name):
            teams.append(team)
    if teams:
        for t in teams:
            print(f"  {t.place_string or '?':>4s} {t.name:<16s} Score: {t.score}")
    else:
        print("  No team data (FFA game or not populated)")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="QMP Client — read Xemu guest memory")
    parser.add_argument("host", nargs="?", default="localhost", help="QMP host")
    parser.add_argument("port", nargs="?", type=int, default=QMPClient.DEFAULT_PORT,
                        help="QMP port")
    args = parser.parse_args()

    print(f"Connecting to QMP at {args.host}:{args.port}...")
    client = QMPClient(args.host, args.port)
    if not client.connect():
        print("Failed to connect. Is Xemu running with -qmp flag?")
        print(f"  Expected: -qmp tcp:{args.host}:{args.port},server,nowait")
        sys.exit(1)
    print("Connected!\n")

    _test_pgcr(client)

    client.disconnect()
    print("\nDone.")
