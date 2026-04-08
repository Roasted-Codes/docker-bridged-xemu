#!/usr/bin/env python3
"""
Halo 2 Stats Reader - Cross-platform post-game stats via XBDM/QMP

Reads Halo 2 post-game statistics from Xbox/Xemu via XBDM (port 731)
or QMP (QEMU Machine Protocol).

Usage:
    # Read post-game stats (default: tries PGCR Display first, falls back to PCR)
    python halo2_stats.py --host 172.20.0.51

    # Watch for game completions and auto-save history
    python halo2_stats.py --host 172.20.0.51 --watch

    # JSON output
    python halo2_stats.py --host 172.20.0.51 --json

    # QMP mode (reads same PGCR data via QEMU Machine Protocol)
    python halo2_stats.py --host 172.20.0.10 --qmp 4444
"""

import argparse
import hashlib
import json
import os
import re
import select
import signal
import struct
import sys
import time
from datetime import datetime
from typing import List, Optional, Dict, Any

from xbdm_client import XBDMClient, XBDMNotificationListener
from halo2_structs import (
    PCRPlayerStats,
    GameType,
    GameTeam,
    GAMETYPE_NAMES,
    TeamStats,
    calculate_pcr_address,
    calculate_pgcr_display_address,
    calculate_team_data_address,
    calculate_pgcr_display_team_address,
    get_address,
    decode_medals,
    PCR_PLAYER_SIZE,
    PGCR_DISPLAY_SIZE,
    TEAM_DATA_STRIDE,
    MAX_TEAMS,
    PGCR_BREAKPOINT_ADDR,
    PGCR_DISPLAY_HEADER,
    PGCR_DISPLAY_HEADER_SIZE,
    PGCR_DISPLAY_GAMETYPE_ADDR,
)
from addresses import DISCOVERED_ADDRESSES


def _is_valid_player_name(name_bytes: bytes) -> bool:
    """
    Check if raw UTF-16LE name bytes represent a valid Xbox gamertag.

    Rejects garbage/uninitialized memory by checking:
    - At least 1 character
    - All characters are printable ASCII or common Unicode (0x20-0x7E range)
    - First null terminator within reasonable range
    """
    try:
        name = name_bytes.decode('utf-16-le').rstrip('\x00')
    except (UnicodeDecodeError, ValueError):
        return False
    if not name or len(name) < 1:
        return False
    # Xbox gamertags are ASCII printable (letters, digits, spaces, some symbols)
    return all(0x20 <= ord(c) <= 0x7E for c in name)


class Halo2StatsReader:
    """
    Reads Halo 2 statistics from Xbox memory via XBDM.

    Uses the PCR (Post-game Carnage Report) structure at address 0x55CAF0.
    This structure contains player stats that work during and after games.
    """

    MAX_PLAYERS = 16

    def __init__(self, client: XBDMClient, verbose: bool = False):
        self.client = client
        self.verbose = verbose
        self._last_error: Optional[str] = None
        self._variant_info = None  # Reserved for future use

    def log(self, message: str):
        """Print message if verbose mode enabled."""
        if self.verbose:
            print(f"[DEBUG] {message}")

    def read_player(self, player_index: int) -> Optional[PCRPlayerStats]:
        """
        Read stats for a single player using PCR structure.

        Args:
            player_index: Player slot (0-15)

        Returns:
            PCRPlayerStats if successful, None on error
        """
        addr = calculate_pcr_address(player_index)
        self.log(f"Reading player {player_index} from 0x{addr:08X}")

        data = self.client.read_memory(addr, PCR_PLAYER_SIZE)
        if not data:
            self._last_error = f"Failed to read player {player_index} at 0x{addr:08X}"
            return None

        try:
            stats = PCRPlayerStats.from_bytes(data)
            if stats.player_name:
                self.log(f"  Found: {stats.player_name} - K:{stats.kills} D:{stats.deaths}")
            return stats
        except Exception as e:
            self._last_error = f"Failed to parse player {player_index}: {e}"
            return None

    def read_all_players(self) -> List[PCRPlayerStats]:
        """Read stats for all 16 player slots."""
        players = []
        for i in range(self.MAX_PLAYERS):
            player = self.read_player(i)
            if player:
                players.append(player)
        return players

    def read_active_players(self) -> List[PCRPlayerStats]:
        """Read stats only for players with valid (printable ASCII) names."""
        players = []
        for i in range(self.MAX_PLAYERS):
            player = self.read_player(i)
            if player and player.player_name.strip():
                if all(0x20 <= ord(c) <= 0x7E for c in player.player_name):
                    players.append(player)
        return players

    def get_snapshot(self) -> Dict[str, Any]:
        """
        Get a complete snapshot of current game state.

        Returns a dictionary ready for JSON serialization.
        """
        players = self.read_active_players()

        return {
            "timestamp": datetime.now().isoformat(),
            "player_count": len(players),
            "players": [p.to_dict() for p in players],
        }

    @property
    def last_error(self) -> Optional[str]:
        return self._last_error

    # =========================================================================
    # PCR Probing and PGCR Display Methods
    # =========================================================================

    def probe_pcr_populated(self) -> bool:
        """
        Lightweight check: is the PCR populated with game data?

        Reads only the first player's name field (32 bytes at 0x55CAF0).
        Validates the name contains printable characters (not garbage memory).
        """
        addr = calculate_pcr_address(0)
        data = self.client.read_memory(addr, 32)
        if not data:
            return False
        return _is_valid_player_name(data)

    def read_all_players_indexed(self) -> List[Optional[PCRPlayerStats]]:
        """Read all 16 player slots, preserving slot indices (None for empty)."""
        players = []
        for i in range(self.MAX_PLAYERS):
            player = self.read_player(i)
            if (player and player.player_name.strip()
                    and all(0x20 <= ord(c) <= 0x7E for c in player.player_name)):
                players.append(player)
            else:
                players.append(None)
        return players

    def read_pgcr_display_player(self, player_index: int) -> Optional[PCRPlayerStats]:
        """
        Read PGCR display stats for a single player.

        The PGCR Display uses the same pcr_stat_player layout as PCR,
        just at a different base address (0x56B990 instead of 0x55CAF0).
        Only populated during the post-game carnage report screen.
        """
        addr = calculate_pgcr_display_address(player_index)
        self.log(f"Reading PGCR display player {player_index} from 0x{addr:08X}")

        data = self.client.read_memory(addr, PCR_PLAYER_SIZE)
        if not data:
            return None

        try:
            stats = PCRPlayerStats.from_bytes(data)
            if stats.player_name:
                return stats
            return None
        except Exception as e:
            self.log(f"Failed to parse PGCR display {player_index}: {e}")
            return None

    def read_active_pgcr_display(self) -> List[PCRPlayerStats]:
        """Read PGCR display stats for all players with valid (printable) names."""
        players = []
        for i in range(self.MAX_PLAYERS):
            player = self.read_pgcr_display_player(i)
            if player and player.player_name.strip():
                # Validate the name is printable ASCII (not garbage memory)
                if all(0x20 <= ord(c) <= 0x7E for c in player.player_name):
                    players.append(player)
        return players

    def probe_pgcr_display_populated(self) -> bool:
        """
        Lightweight check: is the PGCR display populated with real data?

        Reads the first player's name (32 bytes at 0x56B990) and validates
        it contains printable characters (not garbage/uninitialized memory).
        """
        addr = calculate_pgcr_display_address(0)
        # Player name is at offset 0x00 within the player record
        data = self.client.read_memory(addr, 32)
        if not data:
            return False
        return _is_valid_player_name(data)

    # =========================================================================
    # Gametype and Team Methods
    # =========================================================================

    def read_pgcr_header(self) -> Optional[bytes]:
        """Read the full PGCR Display header (0x90 bytes at 0x56B900).

        The header contains the gametype enum at +0x84, but the other 132 bytes
        are undocumented. This method returns raw bytes for investigation.
        """
        addr = PGCR_DISPLAY_HEADER
        self.log(f"Reading PGCR header from 0x{addr:08X} ({PGCR_DISPLAY_HEADER_SIZE} bytes)")
        data = self.client.read_memory(addr, PGCR_DISPLAY_HEADER_SIZE)
        if not data or len(data) < PGCR_DISPLAY_HEADER_SIZE:
            return None
        return data

    def read_gametype(self) -> Optional[GameType]:
        """Read gametype enum from PGCR Display header at 0x56B984.

        WARNING: This address is STALE on docker-bridged-xemu — it retains the
        gametype from the PREVIOUS game, not the current one. Use
        read_gametype_discovered() as the primary source. This is a fallback.
        """
        addr = PGCR_DISPLAY_GAMETYPE_ADDR
        self.log(f"Reading gametype from 0x{addr:08X}")
        data = self.client.read_memory(addr, 4)
        if not data or len(data) < 4:
            return None
        value = struct.unpack('<I', data)[0]
        try:
            gt = GameType(value)
            return gt if gt != GameType.NONE else None
        except ValueError:
            self.log(f"Unknown gametype value: {value}")
            return None

    # .data section VA start — used for linear physical reads that bypass
    # stale page table entries (see _read_via_data_section_offset)
    _DATA_SECTION_VA = 0x46D6E0

    def _read_via_data_section_offset(self, va: int, length: int = 4) -> Optional[bytes]:
        """Read a .data section address via linear physical offset.

        Xbox page table entries for individual pages within .data can be
        stale/wrong between games, but the section is physically contiguous.
        Translates the .data section START VA to physical, then adds the
        fixed offset to reach the target address.

        Only works for QMP clients that expose translate_va and _read_physical.
        """
        if not hasattr(self.client, 'translate_va') or not hasattr(self.client, '_read_physical'):
            return None
        phys_start = self.client.translate_va(self._DATA_SECTION_VA)
        if phys_start is None:
            return None
        offset = va - self._DATA_SECTION_VA
        if offset < 0:
            return None
        return self.client._read_physical(phys_start + offset, length)

    def read_gametype_discovered(self) -> Optional[GameType]:
        """Read gametype from discovered address 0x52ED24.

        This is the ONLY address in the entire .data section that holds the
        correct gametype enum for all 7 gametypes (CTF=1, Slayer=2, Oddball=3,
        KOTH=4, Juggernaut=7, Territories=8, Assault=9). Confirmed via 7-way
        cross-reference of full .data section snapshots (Feb 2026).

        IMPORTANT: Uses linear physical offset from .data section start,
        NOT per-page gva2gpa translation. The Xbox page table entries for
        individual pages within .data can be stale/wrong, but the section
        is physically contiguous. Translate the .data start VA once, then
        add the fixed offset to get the correct physical address.

        Returns None if the address reads as 0 (not yet populated or cleared).
        """
        addr = DISCOVERED_ADDRESSES.get("gametype_confirmed", 0)
        if not addr:
            return None

        # Read via linear physical offset from .data start (bypasses stale PTEs)
        data = self._read_via_data_section_offset(addr)
        if not data or len(data) < 4:
            # Fallback to direct VA translation
            data = self.client.read_memory(addr, 4)
        if not data or len(data) < 4:
            return None
        value = struct.unpack('<I', data)[0]
        try:
            gt = GameType(value)
            if gt != GameType.NONE:
                self.log(f"Gametype from 0x{addr:08X}: {value} -> {gt.name}")
                return gt
        except ValueError:
            self.log(f"Unknown gametype value at 0x{addr:08X}: {value}")
        return None

    # variant_info: variant name (UTF-16LE) at physical 0x036295F4, gametype byte
    # at +0x40. Map content path (ASCII, e.g. "t:\$C\<title_id>\<map_name>") lives
    # 0xA4 bytes before the variant name. Verified stable across lobby, in-game,
    # and PGCR screen via QMP scan (2026-03-28).
    VARIANT_INFO_PHYSICAL = 0x036295F4
    VARIANT_INFO_SIZE = 0x50         # variant name (32 bytes) + gametype at +0x40
    VARIANT_INFO_MAP_PHYSICAL = 0x03629550  # map content path (0xA4 before variant name)
    VARIANT_INFO_MAP_SIZE = 0xA4

    MAP_NAMES = {
        "beavercreek": "Beaver Creek",
        "burial_mounds": "Burial Mounds",
        "coagulation": "Coagulation",
        "colossus": "Colossus",
        "cyclotron": "Ivory Tower",
        "foundation": "Foundation",
        "headlong": "Headlong",
        "lockout": "Lockout",
        "midship": "Midship",
        "waterworks": "Waterworks",
        "zanzibar": "Zanzibar",
        "ascension": "Ascension",
        "deltatap": "Sanctuary",
        "dune": "Relic",
        "elongation": "Elongation",
        "gemini": "Gemini",
        "triplicate": "Terminal",
        "turf": "Turf",
        "containment": "Containment",
        "warlock": "Warlock",
        "street_sweeper": "District",
        "needle": "Uplift",
        "backwash": "Backwash",
    }

    def read_variant_info(self) -> Optional[Dict[str, str]]:
        """Read variant name and map name from variant_info struct in physical memory.

        Returns dict with 'variant' and 'map' keys, or None on failure.
        Only works via QMP (direct physical reads).
        """
        if not hasattr(self.client, '_read_physical'):
            self.log("variant_info requires QMP client with _read_physical")
            return None

        data = self.client._read_physical(self.VARIANT_INFO_PHYSICAL, self.VARIANT_INFO_SIZE)
        if not data or len(data) < self.VARIANT_INFO_SIZE:
            self.log(f"variant_info read failed (got {len(data) if data else 0} bytes)")
            return None

        # Parse variant name (UTF-16LE, 16 chars at offset 0x00)
        try:
            variant_name = data[0:32].decode('utf-16-le').rstrip('\x00')
            # Strip private-use Unicode chars (e.g. \ue008) that appear as trailing garbage
            variant_name = ''.join(c for c in variant_name if ord(c) < 0xE000 or ord(c) > 0xF8FF).strip()
        except Exception:
            variant_name = ""

        # Parse map name from content path at separate physical address
        # Format: "t:\$C\<title_id>\<map_name>" e.g. "t:\$C\4d53006400000003\backwash"
        map_name = ""
        map_data = self.client._read_physical(self.VARIANT_INFO_MAP_PHYSICAL, self.VARIANT_INFO_MAP_SIZE)
        if map_data:
            try:
                content_path = map_data.split(b'\x00')[0].decode('ascii')
                parts = content_path.replace('\\', '/').split('/')
                internal = parts[-1] if parts else ""
                map_name = self.MAP_NAMES.get(internal, internal)
            except Exception:
                pass

        if variant_name or map_name:
            self.log(f"variant_info: variant=\"{variant_name}\" map=\"{map_name}\"")
            return {"variant": variant_name, "map": map_name}

        self.log("variant_info: empty (no game active?)")
        return None

    def read_teams(self) -> List[TeamStats]:
        """Read team data, trying PGCR Display location first then PCR fallback.

        PGCR Display teams: 0x56CAD0 (after 16 PGCR player records)
        PCR teams: 0x55DC30 (after 16 PCR player records) — empty on docker-bridged-xemu
        """
        # Try PGCR Display team data first (primary)
        teams = self._read_teams_from(calculate_pgcr_display_team_address)
        if teams:
            return teams
        # Fallback to PCR team data
        return self._read_teams_from(calculate_team_data_address)

    def _read_teams_from(self, addr_func) -> List[TeamStats]:
        """Read team data from a given address calculator."""
        teams = []
        for i in range(MAX_TEAMS):
            addr = addr_func(i)
            data = self.client.read_memory(addr, TEAM_DATA_STRIDE)
            if not data:
                continue
            try:
                team = TeamStats.from_bytes(data, index=i)
                # Validate team name is real (not garbage memory)
                if team.name.strip() and all(0x20 <= ord(c) <= 0x7E for c in team.name):
                    teams.append(team)
            except Exception as e:
                self.log(f"Failed to parse team {i}: {e}")
        return teams

def format_player_summary(player: PCRPlayerStats) -> str:
    """Format a single player's stats as a readable line."""
    name = player.player_name[:16].ljust(16)
    k = player.kills
    d = player.deaths
    a = player.assists
    kd = k / max(d, 1)

    return f"{name} K:{k:3d} D:{d:3d} A:{a:3d} K/D:{kd:.2f}"


def print_scoreboard(players: List[PCRPlayerStats]):
    """Print a formatted scoreboard to console."""
    if not players:
        print("No players found in game.")
        return

    print("\n" + "=" * 60)
    print(" HALO 2 STATS")
    print("=" * 60)

    # Sort by kills descending
    sorted_players = sorted(players, key=lambda p: p.kills, reverse=True)

    for i, player in enumerate(sorted_players, 1):
        print(f" {i:2d}. {format_player_summary(player)}")

    print("=" * 60)
    print()


def compute_game_fingerprint(players) -> str:
    """
    Compute a fingerprint string for deduplication.

    Uses player names + all available stats to create a unique identifier.
    Includes score_string, shots, headshots, and gametype values to
    distinguish games with identical K/D/A (e.g. solo 0-0-0 CTF games).

    """
    parts = []
    for p in sorted(players, key=lambda x: x.player_name):
        fields = f"{p.player_name}:{p.kills}:{p.deaths}:{p.assists}:{p.suicides}"
        # Include additional fields to distinguish otherwise-identical games
        if hasattr(p, 'score_string'):
            fields += f":{p.score_string}"
        if hasattr(p, 'total_shots'):
            fields += f":{p.total_shots}:{p.shots_hit}:{p.headshots}"
        if hasattr(p, 'gametype_value0'):
            fields += f":{p.gametype_value0}:{p.gametype_value1}"
        parts.append(fields)
    content = "|".join(parts)
    return hashlib.md5(content.encode('utf-8')).hexdigest()


def build_snapshot(players,
                   source: str = "pcr",
                   gametype_id: Optional[int] = None,
                   teams: Optional[List[TeamStats]] = None,
                   map_name: Optional[str] = None,
                   variant_name: Optional[str] = None) -> Dict[str, Any]:
    """
    Build a complete game snapshot dictionary.

    Args:
        players: List of active player stats (PCRPlayerStats)
        source: Data source identifier ("pcr" or "pgcr_display")
        gametype_id: Gametype enum value from memory (e.g. GameType.SLAYER = 2)
        teams: Optional list of TeamStats from team data area
        map_name: Map display name (e.g. "Lockout")
        variant_name: Game variant name (e.g. "Team Slayer")
    """
    fingerprint = compute_game_fingerprint(players)

    # Determine gametype string from enum value
    gametype = None
    if gametype_id is not None and gametype_id > 0:
        try:
            gametype = GAMETYPE_NAMES.get(GameType(gametype_id), f"Unknown({gametype_id})").lower()
        except ValueError:
            pass

    timestamp = datetime.now().isoformat()

    # Include timestamp in stored fingerprint so games with identical stats
    # (e.g. all 0-0-0 scores) are never treated as duplicates during import.
    unique_fingerprint = hashlib.md5(
        (fingerprint + ":" + timestamp).encode('utf-8')
    ).hexdigest()

    snapshot = {
        "schema_version": 3,
        "timestamp": timestamp,
        "fingerprint": unique_fingerprint,
        "source": source,
        "gametype": gametype,
        "gametype_id": gametype_id,
        "player_count": len(players),
        "players": [p.to_dict() for p in players],
    }

    if map_name:
        snapshot["map"] = map_name
    if variant_name:
        snapshot["variant"] = variant_name

    # Add labeled gametype stats per player
    if gametype:
        for i, p in enumerate(players):
            snapshot["players"][i]["gametype_stats"] = p.get_gametype_stats(gametype)

    # Add team data if present
    if teams:
        snapshot["teams"] = [t.to_dict() for t in teams]

    return snapshot


def save_game_history(snapshot: Dict[str, Any], history_dir: str) -> str:
    """
    Save a game snapshot to the history directory.

    Args:
        snapshot: Game data dictionary (from build_snapshot)
        history_dir: Directory path for history files

    Returns:
        Path to the saved file
    """
    os.makedirs(history_dir, exist_ok=True)

    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    fingerprint = snapshot.get("fingerprint", "00000000")[:8]
    filename = f"{timestamp}_{fingerprint}.json"
    filepath = os.path.join(history_dir, filename)

    with open(filepath, 'w') as f:
        json.dump(snapshot, f, indent=2)

    return filepath


def dump_pgcr_raw(client, history_dir: str, fingerprint: str) -> Optional[str]:
    """Dump raw hex of PGCR header, player records, and team structs to a file."""
    regions = [
        ("PGCR Header", PGCR_DISPLAY_HEADER, PGCR_DISPLAY_HEADER_SIZE),
    ]
    for i in range(16):
        addr = calculate_pgcr_display_address(i)
        regions.append((f"Player {i}", addr, PCR_PLAYER_SIZE))
    for i in range(MAX_TEAMS):
        addr = calculate_pgcr_display_team_address(i)
        regions.append((f"Team {i}", addr, TEAM_DATA_STRIDE))

    lines = []
    for label, addr, length in regions:
        try:
            data = client.read_memory(addr, length)
            if not data:
                lines.append(f"=== {label} (0x{addr:08X}, 0x{length:X} bytes) === NO DATA")
                continue
            lines.append(f"=== {label} (0x{addr:08X}, 0x{length:X} bytes) ===")
            for i in range(0, len(data), 16):
                chunk = data[i:i+16]
                hex_part = " ".join(f"{b:02X}" for b in chunk)
                ascii_part = "".join(chr(b) if 0x20 <= b < 0x7F else "." for b in chunk)
                lines.append(f"  {addr + i:08X}  {hex_part:<48}  {ascii_part}")
            lines.append("")
        except Exception as e:
            lines.append(f"=== {label} (0x{addr:08X}) === ERROR: {e}")

    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    fp_short = fingerprint[:8] if fingerprint else "unknown"
    filepath = os.path.join(history_dir, f"{timestamp}_{fp_short}_memdump.txt")
    with open(filepath, 'w') as f:
        f.write("\n".join(lines))
    return filepath


def run_watch_mode(reader: 'Halo2StatsReader', args) -> None:
    """
    Watch mode: continuously monitor for game completions.

    Uses fingerprint-based deduplication — no state machine needed.
    Each poll: check if PGCR Display (or PCR) has data with a new fingerprint.
    If the fingerprint changed, it's a new game result — capture and save.

    Probes PGCR Display first (0x56B900+0x90), falls back to PCR (0x55CAF0).
    """
    history_dir = args.history_dir
    os.makedirs(history_dir, exist_ok=True)

    # Seed last_fingerprint from current PGCR memory so we don't re-capture
    # stale data left over from a previous game on startup.
    last_fingerprint = None
    try:
        if reader.probe_pgcr_display_populated():
            seed_players = reader.read_active_pgcr_display()
            if seed_players:
                last_fingerprint = compute_game_fingerprint(seed_players)
                print(f"[Watch] Seeded fingerprint from current PGCR memory: {last_fingerprint[:8]}")
    except Exception:
        pass

    print(f"Watch mode active. Polling every {args.watch_interval}s.")
    print(f"History will be saved to: {os.path.abspath(history_dir)}/")
    print("Press Ctrl+C to stop.\n")

    while True:
        try:
            # Reconnect if connection was lost (e.g. broken pipe, xemu restart)
            if hasattr(reader.client, 'is_connected') and not reader.client.is_connected:
                print("[Watch] Connection lost, reconnecting...")
                reader.client.reconnect()
                print("[Watch] Reconnected!")

            players = None
            source = None

            # Try PGCR Display first (reliable), then PCR (may be empty)
            if reader.probe_pgcr_display_populated():
                display_players = reader.read_active_pgcr_display()
                if display_players:
                    players = display_players
                    source = "pgcr_display"

            if not players and reader.probe_pcr_populated():
                all_indexed = reader.read_all_players_indexed()
                pcr_players = [p for p in all_indexed if p is not None]
                if pcr_players:
                    players = pcr_players
                    source = "pcr"

            if players:
                fingerprint = compute_game_fingerprint(players)
                if fingerprint != last_fingerprint:
                    # Stability check: wait briefly and re-read to avoid
                    # transitional captures (e.g. stale player data + new
                    # team data while PGCR memory is being overwritten)
                    time.sleep(1)
                    recheck_players = None
                    if reader.probe_pgcr_display_populated():
                        recheck_players = reader.read_active_pgcr_display()
                    if recheck_players:
                        recheck_fp = compute_game_fingerprint(recheck_players)
                        if recheck_fp != fingerprint:
                            # Data is still changing — skip this poll
                            continue
                        players = recheck_players

                    last_fingerprint = fingerprint

                    # Clear VA→PA cache — page tables change between games,
                    # so cached translations point to wrong physical pages
                    if hasattr(reader.client, 'clear_va_cache'):
                        reader.client.clear_va_cache()

                    # Save full RAM snapshot if requested (must be before re-reading)
                    if args.save_ram:
                        if hasattr(reader.client, 'save_ram'):
                            ram_filepath = os.path.abspath(os.path.join(history_dir, f"{fingerprint}_ram.bin"))
                            print(f"[Watch] Saving RAM snapshot...")
                            try:
                                if reader.client.save_ram(ram_filepath):
                                    try:
                                        ram_size = os.path.getsize(ram_filepath) / 1024 / 1024
                                        print(f"  -> RAM snapshot saved ({ram_size:.1f} MB)")
                                    except:
                                        print(f"  -> RAM snapshot saved to {os.path.basename(ram_filepath)}")
                                else:
                                    print(f"  -> RAM snapshot save failed (not supported on this connection)")
                            except Exception as e:
                                print(f"  -> RAM snapshot save error: {e}")
                        else:
                            print("[Watch] --save-ram requires QMP mode")

                    # Re-read players and teams with fresh VA translations
                    if reader.probe_pgcr_display_populated():
                        fresh_players = reader.read_active_pgcr_display()
                        if fresh_players:
                            players = fresh_players
                    teams = reader.read_teams()

                    # Read gametype from discovered address (0x52ED24).
                    # Retry up to 3x with 500ms delay if not populated yet.
                    gametype_id = None
                    for _gt_attempt in range(3):
                        gametype_id = reader.read_gametype_discovered()
                        if gametype_id:
                            break
                        time.sleep(0.5)
                    if not gametype_id:
                        gametype_id = reader.read_gametype()  # stale PGCR header fallback
                    gt_label = GAMETYPE_NAMES.get(gametype_id, "Unknown") if gametype_id else "Unknown"
                    print(f"[Gametype] {gt_label} ({gametype_id.value if gametype_id else '?'})")
                    vinfo = reader.read_variant_info()
                    snapshot = build_snapshot(
                        players, source=source,
                        gametype_id=gametype_id.value if gametype_id else None,
                        teams=teams,
                        map_name=vinfo.get("map") if vinfo else None,
                        variant_name=vinfo.get("variant") if vinfo else None,
                    )

                    gt_label = GAMETYPE_NAMES.get(gametype_id, "Unknown") if gametype_id else "Unknown"
                    map_str = f", map: {vinfo['map']}" if vinfo and vinfo.get('map') else ""
                    print(f"[Watch] Game detected! ({len(players)} players, source: {source}, gametype: {gt_label}{map_str})")

                    # Determine gametype label for display
                    gametype_for_display = args.gametype
                    if not gametype_for_display and gametype_id and gametype_id.value > 0:
                        gametype_for_display = GAMETYPE_NAMES.get(gametype_id, str(gametype_id)).lower()

                    if args.json:
                        print(json.dumps(snapshot, indent=2))
                    elif args.pgcr:
                        print_pgcr_report(players, teams, gametype_for_display)
                    else:
                        print_scoreboard_rich(players, gametype=gametype_for_display, teams=teams)

                    filepath = save_game_history(snapshot, history_dir)
                    print(f"  -> Saved to {filepath}")

                    # Save annotated PGCR dump + raw memory for struct analysis
                    fp8 = fingerprint[:8] if len(fingerprint) >= 8 else fingerprint
                    try:
                        annotated_path = dump_pgcr_annotated(reader.client, history_dir, fp8)
                        if annotated_path:
                            print(f"  -> Annotated hex dump saved to {os.path.basename(annotated_path)}")
                    except Exception as e:
                        print(f"  -> Annotated hex dump failed: {e}")

                    try:
                        dump_path = dump_pgcr_raw(reader.client, history_dir, fingerprint)
                        if dump_path:
                            print(f"  -> Raw memory dump saved to {os.path.basename(dump_path)}\n")
                    except Exception as e:
                        print(f"  -> Raw memory dump failed: {e}\n")

        except KeyboardInterrupt:
            raise
        except Exception as e:
            print(f"[Watch] Error: {e}")

        time.sleep(args.watch_interval)


def _parse_thread_id(notification: str) -> Optional[int]:
    """Extract thread ID from breakpoint notification.

    Example: 'break addr=0x0023975c thread=28 stop' -> 28
    """
    m = re.search(r'thread=(\d+)', notification)
    return int(m.group(1)) if m else None


def run_watch_mode_breakpoint(reader: 'Halo2StatsReader', client: XBDMClient, args) -> None:
    """
    Watch mode using XBDM breakpoint at 0x23975C for instant game-end detection.

    Sets a hardware breakpoint on the PGCR clear function. When a game ends,
    the engine calls this function, the breakpoint fires, and the Xbox halts.
    We resume execution (continue thread + go per SDK), then poll until PGCR
    Display has valid player data and capture the stats.

    Much faster than polling (instant detection vs 3s delay).
    """
    history_dir = args.history_dir
    os.makedirs(history_dir, exist_ok=True)

    last_fingerprint = None
    bp_addr_hex = f"0x{PGCR_BREAKPOINT_ADDR:08X}"

    # Clear any stale breakpoints first
    client.clear_all_breakpoints()
    try:
        client.continue_execution()
    except Exception:
        pass
    time.sleep(0.2)

    # Set breakpoint
    print(f"Setting breakpoint at {bp_addr_hex}...")
    if not client.set_breakpoint(PGCR_BREAKPOINT_ADDR):
        print("ERROR: Failed to set breakpoint. Falling back to polling mode.")
        run_watch_mode(reader, args)
        return

    # Open notification listener
    print("Opening notification listener...")
    listener = XBDMNotificationListener(client.host, client.port, timeout=10.0)
    if not listener.connect():
        print("ERROR: Failed to connect notification listener. Falling back to polling mode.")
        client.clear_breakpoint(PGCR_BREAKPOINT_ADDR)
        run_watch_mode(reader, args)
        return

    print(f"Breakpoint watch mode active at {bp_addr_hex}.")
    print(f"History will be saved to: {os.path.abspath(history_dir)}/")
    print("Waiting for game end (breakpoint trigger)...")
    print("Press Ctrl+C to stop.\n")

    try:
        while True:
            # Use select() to reliably block on the notification socket.
            # This prevents the spin-loop bug where _recv_line returns None
            # instantly on a degraded connection.
            sock = listener._socket
            if sock is None or not listener._connected:
                print("[Breakpoint] Notification connection lost, exiting.")
                break

            try:
                readable, _, _ = select.select([sock], [], [], 30.0)
            except (OSError, ValueError):
                print("[Breakpoint] Socket error, exiting.")
                break

            if not readable:
                # 30-second timeout, no data — just keep waiting
                continue

            # Data available on socket
            notification = listener.wait_for_notification(timeout=2)
            if not notification:
                print("[Breakpoint] Connection appears dead, exiting.")
                break

            notification_stripped = notification.strip()
            ts = time.strftime("%H:%M:%S")

            # Filter: only act on 'break' notifications for our address
            if 'break' not in notification.lower():
                # Informational (execution started/stopped) — ignore
                continue

            addr_match = f"{PGCR_BREAKPOINT_ADDR:x}" in notification.lower()
            if not addr_match:
                # Different breakpoint address — resume and ignore
                print(f"[{ts}] Other breakpoint, resuming: {notification_stripped}")
                thread_id = _parse_thread_id(notification)
                if thread_id is not None:
                    client.continue_thread(thread_id)
                client.continue_execution()
                continue

            print(f"[{ts}] Breakpoint fired at {bp_addr_hex}!")

            # Clear VA→PA cache — page tables change between games
            if hasattr(reader.client, 'clear_va_cache'):
                reader.client.clear_va_cache()

            # The breakpoint fires at the ENTRY of the PGCR clear function.
            # The Xbox is halted, so PGCR data still has the current game's
            # stats. Read everything NOW (while halted) before resuming.
            # CRITICAL: gametype at 0x52ED24 must be read while halted —
            # the clear function will zero it after we resume.
            players = None
            teams = None
            gametype_id = None
            try:
                players = reader.read_active_pgcr_display()
                teams = reader.read_teams()
                gametype_id = reader.read_gametype_discovered()
            except Exception as e:
                print(f"[{ts}] Error reading stats while halted: {e}")

            # Now resume execution: DmContinueThread before DmGo per SDK
            thread_id = _parse_thread_id(notification)
            if thread_id is not None:
                client.continue_thread(thread_id)
            client.continue_execution()

            if not players:
                print(f"[{ts}] No valid players in PGCR (may be game start)")
                continue

            fingerprint = compute_game_fingerprint(players)
            if fingerprint == last_fingerprint:
                print(f"[{ts}] Same game (duplicate fingerprint), skipping.")
                continue

            last_fingerprint = fingerprint

            # Save full RAM snapshot if requested (after execution resumed)
            fp8 = fingerprint[:8] if len(fingerprint) >= 8 else fingerprint
            if args.save_ram:
                if hasattr(reader.client, 'save_ram'):
                    ram_filepath = os.path.abspath(os.path.join(history_dir, f"{fp8}_ram.bin"))
                    print(f"[{ts}] Saving RAM snapshot...")
                    try:
                        if reader.client.save_ram(ram_filepath):
                            try:
                                ram_size = os.path.getsize(ram_filepath) / 1024 / 1024
                                print(f"  -> RAM snapshot saved ({ram_size:.1f} MB)")
                            except:
                                print(f"  -> RAM snapshot saved to {os.path.basename(ram_filepath)}")
                        else:
                            print(f"  -> RAM snapshot save failed (not supported on this connection)")
                    except Exception as e:
                        print(f"  -> RAM snapshot save error: {e}")

            try:
                # gametype_id was already read while halted above;
                # fall back to PGCR header only if discovered addr was empty
                if not gametype_id:
                    gametype_id = reader.read_gametype()
                gt_label = GAMETYPE_NAMES.get(gametype_id, "Unknown") if gametype_id else "Unknown"
                print(f"[Gametype] {gt_label} ({gametype_id.value if gametype_id else '?'})")
                vinfo = reader.read_variant_info()

                snapshot = build_snapshot(
                    players, source="pgcr_display",
                    gametype_id=gametype_id.value if gametype_id else None,
                    teams=teams,
                    map_name=vinfo.get("map") if vinfo else None,
                    variant_name=vinfo.get("variant") if vinfo else None,
                )

                map_str = f", map: {vinfo['map']}" if vinfo and vinfo.get('map') else ""
                print(f"[{ts}] Game captured! ({len(players)} players{map_str})")

                # Determine gametype label for display
                gametype_for_display = args.gametype
                if not gametype_for_display and gametype_id and gametype_id.value > 0:
                    gametype_for_display = GAMETYPE_NAMES.get(gametype_id, str(gametype_id)).lower()

                if args.json:
                    print(json.dumps(snapshot, indent=2))
                elif args.pgcr:
                    print_pgcr_report(players, teams, gametype_for_display)
                else:
                    print_scoreboard_rich(players, gametype=gametype_for_display, teams=teams)

                filepath = save_game_history(snapshot, history_dir)
                print(f"  -> Saved to {filepath}")

                # Save annotated PGCR dump for struct analysis
                try:
                    annotated_path = dump_pgcr_annotated(reader.client, history_dir, fp8)
                    if annotated_path:
                        print(f"  -> Annotated hex dump saved to {os.path.basename(annotated_path)}\n")
                except Exception as e:
                    print(f"  -> Annotated hex dump failed: {e}\n")

                print("Waiting for next game...\n")
            except Exception as e:
                print(f"[{ts}] Error reading stats: {e}")

    except KeyboardInterrupt:
        print("\nStopping breakpoint watch mode...")
    finally:
        print(f"Clearing breakpoint at {bp_addr_hex}...")
        client.clear_all_breakpoints()
        try:
            client.continue_execution()
        except Exception:
            pass
        listener.close()
        print("Breakpoint cleared, listener closed.")


def print_scoreboard_rich(players: List[PCRPlayerStats],
                          gametype: Optional[str] = None,
                          all_players: Optional[List[Optional[PCRPlayerStats]]] = None,
                          teams: Optional[List[TeamStats]] = None):
    """Print a detailed scoreboard with medals, accuracy, and gametype stats."""
    if not players:
        print("No players found in game.")
        return

    sorted_players = sorted(players, key=lambda p: p.kills, reverse=True)

    # Build slot-index-to-name lookup for killed-by display
    slot_names = {}
    if all_players:
        for idx, p in enumerate(all_players):
            if p and p.player_name.strip():
                slot_names[idx] = p.player_name

    print("\n" + "=" * 72)
    if gametype:
        print(f" HALO 2 POST-GAME CARNAGE REPORT  —  {gametype.upper()}")
    else:
        print(" HALO 2 POST-GAME CARNAGE REPORT")
    print("=" * 72)

    # Print team scores if available
    if teams:
        print("\n TEAM SCORES")
        sorted_teams = sorted(teams, key=lambda t: t.place)
        team_parts = []
        for t in sorted_teams:
            place_label = t.place_string if t.place_string else f"#{t.place + 1}"
            team_parts.append(f" {t.name}: {t.score} ({place_label})")
        print("   ".join(team_parts))

    for i, player in enumerate(sorted_players, 1):
        name = player.player_name[:16].ljust(16)
        k, d, a = player.kills, player.deaths, player.assists
        kd = k / max(d, 1)

        place_str = player.place_string or f"#{player.place}"
        score_str = player.score_string or ""
        try:
            team_label = GameTeam(player.team).name.capitalize()
        except ValueError:
            team_label = f"Team{player.team}"
        print(f"\n {i:2d}. {name}  {place_str:>4s}  Score: {score_str}  [{team_label}]")
        print(f"     K:{k:3d}  D:{d:3d}  A:{a:3d}  S:{player.suicides:2d}  K/D:{kd:.2f}")

        if player.total_shots > 0:
            acc = player.shots_hit / player.total_shots * 100
            print(f"     Accuracy: {acc:.1f}%  ({player.shots_hit}/{player.total_shots} shots, {player.headshots} headshots)")

        if player.medals_earned > 0:
            medal_names = decode_medals(player.medals_earned_by_type)
            if medal_names:
                print(f"     Medals ({player.medals_earned}): {', '.join(medal_names)}")
            else:
                print(f"     Medals: {player.medals_earned}")

        if player.gametype_value0 != 0 or player.gametype_value1 != 0:
            if gametype:
                gt_stats = player.get_gametype_stats(gametype)
                gt_parts = [f"{name}: {val}" for name, val in gt_stats.items() if val != 0]
                if gt_parts:
                    print(f"     {gametype.upper()}: {', '.join(gt_parts)}")
            else:
                print(f"     Gametype Values: {player.gametype_value0}, {player.gametype_value1}")

    print("\n" + "=" * 72)
    print()


def print_pgcr_report(players: List[PCRPlayerStats], teams: Optional[List[TeamStats]], gametype: Optional[str]):
    """Print stats in PGCR Display tabular format (matching in-game screenshots).

    Prints separate sections: TEAM STATS, PLAYER STATS, KILLS, HIT STATS, MEDALS, PvP.
    """
    if not players:
        return

    # Get gametype-specific column labels (keys only — values come from each player)
    gametype_label_keys = None
    has_gt_values = False
    if players and gametype:
        gametype_label_keys = list(players[0].get_gametype_stats(gametype).keys())
        has_gt_values = any(
            any(v != 0 for v in p.get_gametype_stats(gametype).values())
            for p in players
        )

    print("\n" + "=" * 100)
    print("POSTGAME CARNAGE REPORT")
    print("=" * 100)

    # TEAM STATS
    if teams:
        print("\nTEAM STATS")
        print(f"{'Team':<25} {'Place':<10} {'Score':<15}")
        print("-" * 50)
        for team in teams:
            team_name = team.name[:25].ljust(25)
            place_str = team.place_string or f"#{team.place}"
            score_str = team.score_string or str(team.score)
            print(f"{team_name} {place_str:<10} {score_str:<15}")

    # PLAYER STATS (with gametype-specific columns)
    print("\nPLAYER STATS")
    player_stat_cols = ["Player", "Place"]

    if gametype_label_keys and has_gt_values:
        player_stat_cols.extend(gametype_label_keys)

    player_stat_cols.append("Score")

    header = "  ".join(f"{col:<20}" for col in player_stat_cols)
    print(header)
    print("-" * len(header))

    for player in players:
        row_parts = [
            player.player_name[:20].ljust(20),
            (player.place_string or f"#{player.place}").ljust(20)
        ]

        if gametype_label_keys and has_gt_values:
            player_gt = player.get_gametype_stats(gametype)
            for key in gametype_label_keys:
                row_parts.append(str(player_gt.get(key, 0)).ljust(20))

        score_str = player.score_string or str(player.kills)
        row_parts.append(score_str.ljust(20))

        print("  ".join(row_parts))

    # KILLS
    print("\nKILLS")
    print(f"{'Player':<20} {'Kills':<10} {'Assists':<10} {'Deaths':<10} {'Suicides':<10}")
    print("-" * 60)
    for player in players:
        print(f"{player.player_name[:20]:<20} {player.kills:<10} {player.assists:<10} {player.deaths:<10} {player.suicides:<10}")

    # HIT STATS
    if any(p.total_shots > 0 for p in players):
        print("\nHIT STATS")
        print(f"{'Player':<20} {'Shots Hit':<15} {'Shots Fired':<15} {'Hit %':<10} {'Head Shots':<10}")
        print("-" * 70)
        for player in players:
            if player.total_shots > 0:
                hit_pct = (player.shots_hit / player.total_shots * 100) if player.total_shots > 0 else 0
                print(f"{player.player_name[:20]:<20} {player.shots_hit:<15} {player.total_shots:<15} {hit_pct:<10.1f} {player.headshots:<10}")
            else:
                print(f"{player.player_name[:20]:<20} {'0':<15} {'0':<15} {'0':<10} {'0':<10}")

    # MEDALS
    if any(p.medals_earned > 0 for p in players):
        print("\nMEDALS")
        print(f"{'Player':<20} {'Total Medals':<20} {'Types':<40}")
        print("-" * 80)
        for player in players:
            if player.medals_earned > 0:
                from halo2_structs import decode_medals
                medal_names = decode_medals(player.medals_earned_by_type)
                types_str = ", ".join(medal_names[:3]) if medal_names else "?"
                if len(medal_names) > 3:
                    types_str += f" (+{len(medal_names) - 3} more)"
                print(f"{player.player_name[:20]:<20} {player.medals_earned:<20} {types_str:<40}")

    # PLAYER VS. PLAYER (kill matrix)
    if len(players) > 1:
        print("\nPLAYER VS. PLAYER")
        player_names = [p.player_name[:15] for p in players]
        max_name_len = max(len(n) for n in player_names) + 2

        # Header row
        header = "".ljust(max_name_len)
        for name in player_names:
            header += name.ljust(max_name_len)
        print(header)
        print("-" * len(header))

        # Data rows
        for i, player in enumerate(players):
            row = player.player_name[:max_name_len-2].ljust(max_name_len)
            for j in range(len(players)):
                if i == j:
                    row += "-".ljust(max_name_len)
                else:
                    kills = player.killed[j] if j < len(player.killed) else 0
                    row += str(kills).ljust(max_name_len)
            print(row)

    print("\n" + "=" * 100)
    print()


def dump_pgcr_annotated(client, history_dir: str, fingerprint: str) -> Optional[str]:
    """Dump annotated PGCR struct hex dump to file.

    Reads PGCR header, all 16 player records, and 8 team records with field annotations.

    Returns:
        Filepath if successful, None on error
    """
    from addresses import PGCR_DISPLAY_BASE, PGCR_DISPLAY_SIZE, PGCR_DISPLAY_HEADER, PGCR_DISPLAY_HEADER_SIZE, TEAM_DATA_BASE, TEAM_DATA_STRIDE

    regions = [
        ("PGCR Header", PGCR_DISPLAY_BASE, PGCR_DISPLAY_HEADER_SIZE),
    ]

    # 16 player records
    for i in range(16):
        addr = PGCR_DISPLAY_BASE + 0x90 + (i * PGCR_DISPLAY_SIZE)
        regions.append((f"Player {i}", addr, PGCR_DISPLAY_SIZE))

    # 8 team records
    for i in range(8):
        addr = TEAM_DATA_BASE + (i * TEAM_DATA_STRIDE)
        regions.append((f"Team {i}", addr, TEAM_DATA_STRIDE))

    output_path = os.path.join(history_dir, f"{fingerprint}_pgcr_annotated.txt")

    try:
        with open(output_path, 'w') as f:
            for region_name, region_addr, region_size in regions:
                try:
                    data = client.read_memory(region_addr, region_size)
                    if data is None or len(data) < region_size:
                        f.write(f"\n=== {region_name} (0x{region_addr:08X}, 0x{region_size:X} bytes) ===\n")
                        f.write("[Read failed or incomplete]\n")
                        continue
                except Exception as e:
                    f.write(f"\n=== {region_name} (0x{region_addr:08X}, 0x{region_size:X} bytes) ===\n")
                    f.write(f"[Error: {e}]\n")
                    continue

                f.write(f"\n=== {region_name} (0x{region_addr:08X}, 0x{region_size:X} bytes) ===\n")

                # Hex dump with ASCII
                for i in range(0, len(data), 16):
                    chunk = data[i:i+16]
                    hex_str = " ".join(f"{b:02X}" for b in chunk)
                    ascii_str = "".join(chr(b) if 0x20 <= b < 0x7F else "." for b in chunk)
                    f.write(f"  {region_addr + i:08X}  {hex_str:<48}  {ascii_str}\n")

        return output_path
    except Exception as e:
        print(f"ERROR: Failed to dump PGCR annotated: {e}", file=sys.stderr)
        return None


def main():
    signal.signal(signal.SIGTERM, lambda s, f: sys.exit(0))

    parser = argparse.ArgumentParser(
        description="Read Halo 2 post-game statistics via XBDM/QMP",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s --host 192.168.1.100              # Read stats once (rich output)
  %(prog)s --host 127.0.0.1 --watch          # Watch for game completions
  %(prog)s --host 127.0.0.1 --poll 5         # Poll every 5 seconds
  %(prog)s --host 127.0.0.1 --json --save    # JSON output + save to history
  %(prog)s --host 127.0.0.1 --pgcr-display   # Include killed-by data
  %(prog)s --host 127.0.0.1 -g slayer        # Label gametype-specific stats
        """
    )

    parser.add_argument(
        "--host", "-H",
        default="127.0.0.1",
        help="Xbox/Xemu IP address (default: 127.0.0.1)"
    )
    parser.add_argument(
        "--port", "-p",
        type=int,
        default=731,
        help="XBDM port (default: 731)"
    )
    parser.add_argument(
        "--poll", "-P",
        type=float,
        default=0,
        help="Poll interval in seconds (0 = single read)"
    )
    parser.add_argument(
        "--output", "-o",
        help="Output file path for JSON data"
    )
    parser.add_argument(
        "--json", "-j",
        action="store_true",
        help="Output as JSON instead of formatted text"
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Enable verbose debug output"
    )
    parser.add_argument(
        "--timeout", "-t",
        type=float,
        default=5.0,
        help="Connection timeout in seconds (default: 5.0)"
    )
    parser.add_argument(
        "--slow", "-s",
        action="store_true",
        help="Use slower, safer read delays (200ms instead of 50ms)"
    )
    parser.add_argument(
        "--watch", "-w",
        action="store_true",
        help="Watch for game completions and auto-capture PCR stats"
    )
    parser.add_argument(
        "--watch-interval",
        type=float,
        default=3.0,
        help="Seconds between watch-mode probes (default: 3.0)"
    )
    parser.add_argument(
        "--history-dir",
        default="data/history",
        help="Directory for auto-saved game history (default: data/history/)"
    )
    parser.add_argument(
        "--save",
        action="store_true",
        help="Save results to history directory"
    )
    parser.add_argument(
        "--pgcr-display",
        action="store_true",
        help="Also read PGCR display data (killed-by info, only on post-game screen)"
    )
    parser.add_argument(
        "--gametype", "-g",
        choices=["slayer", "ctf", "oddball", "koth", "juggernaut", "territories", "assault"],
        help="Gametype for interpreting gametype-specific stat fields"
    )
    parser.add_argument(
        "--simple",
        action="store_true",
        help="Use simple K/D/A output instead of detailed scoreboard"
    )
    parser.add_argument(
        "--breakpoint", "-b",
        action="store_true",
        help="Use XBDM breakpoint for instant game-end detection (instead of polling)"
    )
    parser.add_argument(
        "--dump-header",
        action="store_true",
        help="Hex dump the PGCR Display header (0x90 bytes) for research"
    )
    parser.add_argument(
        "--qmp",
        type=int,
        metavar="PORT",
        help="Use QMP protocol on PORT for live stats (requires Xemu -qmp flag)"
    )
    parser.add_argument(
        "--pgcr",
        action="store_true",
        help="Print output in PGCR-display format (tabular, matching in-game screenshots)"
    )
    parser.add_argument(
        "--save-ram",
        action="store_true",
        help="Save full 64MB RAM snapshot at each game end (QMP only, creates large files)"
    )

    args = parser.parse_args()

    # Connect via QMP or XBDM
    if args.qmp:
        from qmp_client import QMPClient
        print(f"Connecting to QMP at {args.host}:{args.qmp}...")
        client = QMPClient(args.host, args.qmp, timeout=args.timeout)
        if not client.connect_with_retry():
            # connect_with_retry(max_retries=0) retries forever, so this
            # only triggers if someone overrides max_retries in the future.
            print("ERROR: Failed to connect to QMP", file=sys.stderr)
            print("Make sure Xemu is running with:", file=sys.stderr)
            print(f"  -qmp tcp:0.0.0.0:{args.qmp},server,nowait", file=sys.stderr)
            sys.exit(1)
        print("Connected to QMP!")
    else:
        print(f"Connecting to XBDM at {args.host}:{args.port}...")
        read_delay = 0.2 if args.slow else 0.05  # 200ms slow mode, 50ms normal
        client = XBDMClient(args.host, args.port, timeout=args.timeout, read_delay=read_delay)
        if args.slow:
            print("Using slow mode (200ms between reads)")

        if not client.connect():
            print("ERROR: Failed to connect to XBDM", file=sys.stderr)
            print("Make sure:", file=sys.stderr)
            print("  - For Xemu: xbdm_gdb_bridge is running", file=sys.stderr)
            print("  - For Xbox: Console is on with XBDM enabled", file=sys.stderr)
            print(f"  - Port {args.port} is accessible", file=sys.stderr)
            sys.exit(1)

        print("Connected!")

    reader = Halo2StatsReader(client, verbose=args.verbose)

    try:
        # Dump PGCR header for research
        if args.dump_header:
            header = reader.read_pgcr_header()
            if header:
                print(f"\nPGCR Display Header (0x{PGCR_DISPLAY_HEADER:08X}, {len(header)} bytes):")
                print("=" * 72)
                for offset in range(0, len(header), 16):
                    chunk = header[offset:offset + 16]
                    hex_str = " ".join(f"{b:02X}" for b in chunk)
                    ascii_str = "".join(chr(b) if 0x20 <= b <= 0x7E else "." for b in chunk)
                    print(f"  +0x{offset:02X}: {hex_str:<48s} {ascii_str}")
                # Parse known fields
                gametype_val = struct.unpack('<I', header[0x84:0x88])[0]
                print(f"\nKnown fields:")
                print(f"  +0x84: Gametype enum = {gametype_val}", end="")
                try:
                    print(f" ({GameType(gametype_val).name})")
                except ValueError:
                    print(f" (unknown)")
                # Try interpreting potential strings
                for label, start, end in [("Offset 0x00", 0x00, 0x20), ("Offset 0x20", 0x20, 0x40),
                                          ("Offset 0x40", 0x40, 0x60), ("Offset 0x60", 0x60, 0x80)]:
                    try:
                        text = header[start:end].decode('utf-16-le').rstrip('\x00')
                        if text and all(0x20 <= ord(c) <= 0x7E for c in text):
                            print(f"  {label}: \"{text}\" (UTF-16LE)")
                    except:
                        pass
            else:
                print("Failed to read PGCR header")
            return

        # Watch mode takes over entirely
        if args.watch:
            if args.breakpoint:
                run_watch_mode_breakpoint(reader, client, args)
            else:
                run_watch_mode(reader, args)
            return

        while True:
            # Try PGCR Display first (more reliable), fall back to PCR
            all_indexed = None
            source = "pcr"

            if reader.probe_pgcr_display_populated():
                players = reader.read_active_pgcr_display()
                source = "pgcr_display"
                if players:
                    print("[Note] Using PGCR Display data")
            else:
                players = []

            if not players:
                all_indexed = reader.read_all_players_indexed()
                players = [p for p in all_indexed if p is not None]
                source = "pcr"

            # Read gametype from discovered address, PGCR header fallback
            gametype_enum = reader.read_gametype_discovered() or reader.read_gametype()
            teams = reader.read_teams()
            gametype_id_val = gametype_enum.value if gametype_enum else None
            vinfo = reader.read_variant_info()
            _map = vinfo.get("map") if vinfo else None
            _variant = vinfo.get("variant") if vinfo else None

            if args.json or args.output:
                snapshot = build_snapshot(
                    players, source=source,
                    gametype_id=gametype_id_val, teams=teams,
                    map_name=_map, variant_name=_variant,
                )

                if args.output:
                    with open(args.output, 'w') as f:
                        json.dump(snapshot, f, indent=2)
                    print(f"Stats saved to {args.output}")

                if args.json:
                    print(json.dumps(snapshot, indent=2))
            else:
                # CLI --gametype flag overrides; otherwise use enum-derived name
                gametype_for_display = args.gametype
                if not gametype_for_display and gametype_enum and gametype_enum.value > 0:
                    gametype_for_display = GAMETYPE_NAMES.get(gametype_enum, str(gametype_enum)).lower()

                if args.simple:
                    print_scoreboard(players)
                elif args.pgcr:
                    print_pgcr_report(players, teams, gametype_for_display)
                else:
                    print_scoreboard_rich(
                        players,
                        gametype=gametype_for_display,
                        all_players=all_indexed,
                        teams=teams,
                    )

            if args.save and players:
                snapshot = build_snapshot(
                    players, source=source,
                    gametype_id=gametype_id_val, teams=teams,
                    map_name=_map, variant_name=_variant,
                )
                filepath = save_game_history(snapshot, args.history_dir)
                print(f"Saved to {filepath}")

            if args.poll <= 0:
                break

            time.sleep(args.poll)

    except (KeyboardInterrupt, SystemExit):
        print("\nStopped.")

    finally:
        client.disconnect()


if __name__ == "__main__":
    main()
