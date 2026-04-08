"""
Halo 2 Memory Structures and Addresses

Based on analysis of:
- HaloCaster (xemuh2stats) - live in-game stats
- Yelo Carnage - post-game carnage report stats (via XBDM breakpoints)
- OpenSauce project - canonical structure definitions
  Source: https://github.com/smx-smx/open-sauce/blob/master/OpenSauce/Halo2/Halo2_Xbox/Networking/Statistics.hpp

Memory addresses are for retail Halo 2 Xbox v1.0/v1.5.
"""

import struct
from dataclasses import dataclass, field
from typing import Dict, List, Optional
from enum import IntEnum, IntFlag

from addresses import (
    ADDRESSES, get_address, PCR_PLAYER_SIZE,
    PGCR_DISPLAY_HEADER, PGCR_DISPLAY_HEADER_SIZE,
    PGCR_DISPLAY_GAMETYPE_OFFSET, PGCR_DISPLAY_GAMETYPE_ADDR,
    PGCR_DISPLAY_BASE, PGCR_DISPLAY_SIZE,
    PGCR_DISPLAY_TEAM_BASE, TEAM_DATA_BASE, TEAM_DATA_STRIDE,
    MAX_TEAMS, PGCR_BREAKPOINT_ADDR,
)


# =============================================================================
# Enumerations
# =============================================================================

class GameTeam(IntEnum):
    RED = 0
    BLUE = 1
    YELLOW = 2
    GREEN = 3
    PURPLE = 4
    ORANGE = 5
    BROWN = 6
    PINK = 7
    NEUTRAL = 8


# Gametype enum - readable via XBDM at 0x50224C
# Source: xbox7887 memory research
class GameType(IntEnum):
    NONE = 0
    CTF = 1
    SLAYER = 2
    ODDBALL = 3
    KOTH = 4
    # 5 = race (deprecated), 6 = terminator (deprecated)
    JUGGERNAUT = 7
    TERRITORIES = 8
    ASSAULT = 9  # xbox7887: "bombs"


GAMETYPE_NAMES = {
    GameType.NONE: "None",
    GameType.CTF: "CTF",
    GameType.SLAYER: "Slayer",
    GameType.ODDBALL: "Oddball",
    GameType.KOTH: "KOTH",
    GameType.JUGGERNAUT: "Juggernaut",
    GameType.TERRITORIES: "Territories",
    GameType.ASSAULT: "Assault",
}


# From Yelo Carnage Stats.cs - GameResultsStatistic enum
# From Yelo Carnage Stats.cs - GameResultsMedal enum
class GameResultsMedal(IntEnum):
    """Medal types from game results (from Yelo Carnage)."""
    MULTI_KILL_2 = 0       # Double Kill
    MULTI_KILL_3 = 1       # Triple Kill
    MULTI_KILL_4 = 2       # Overkill
    MULTI_KILL_5 = 3       # Killtacular
    MULTI_KILL_6 = 4       # Killtrocity
    MULTI_KILL_7_OR_MORE = 5  # Killimanjaro+
    SNIPER_KILL = 6
    COLLISION_KILL = 7     # Splatter
    BASH_KILL = 8          # Beat Down
    STEALTH_KILL = 9       # Assassination
    KILLED_VEHICLE = 10
    BOARDED_VEHICLE = 11   # Carjack
    GRENADE_STICK = 12     # Stick
    FIVE_KILLS_IN_A_ROW = 13   # Killing Spree
    TEN_KILLS_IN_A_ROW = 14    # Killing Frenzy
    FIFTEEN_KILLS_IN_A_ROW = 15  # Running Riot
    TWENTY_KILLS_IN_A_ROW = 16   # Rampage
    TWENTY_FIVE_KILLS_IN_A_ROW = 17  # Untouchable
    CTF_FLAG_GRAB = 18
    CTF_FLAG_CARRIER_KILL = 19
    CTF_FLAG_RETURNED = 20
    CTF_BOMB_PLANTED = 21
    CTF_BOMB_CARRIER_KILL = 22
    CTF_BOMB_DEFUSED = 23


# Medal display names (matching GameResultsMedal enum order)
MEDAL_NAMES = {
    GameResultsMedal.MULTI_KILL_2: "Double Kill",
    GameResultsMedal.MULTI_KILL_3: "Triple Kill",
    GameResultsMedal.MULTI_KILL_4: "Overkill",
    GameResultsMedal.MULTI_KILL_5: "Killtacular",
    GameResultsMedal.MULTI_KILL_6: "Killtrocity",
    GameResultsMedal.MULTI_KILL_7_OR_MORE: "Killimanjaro+",
    GameResultsMedal.SNIPER_KILL: "Sniper Kill",
    GameResultsMedal.COLLISION_KILL: "Splatter",
    GameResultsMedal.BASH_KILL: "Beat Down",
    GameResultsMedal.STEALTH_KILL: "Assassination",
    GameResultsMedal.KILLED_VEHICLE: "Destroyed Vehicle",
    GameResultsMedal.BOARDED_VEHICLE: "Carjack",
    GameResultsMedal.GRENADE_STICK: "Stick",
    GameResultsMedal.FIVE_KILLS_IN_A_ROW: "Killing Spree",
    GameResultsMedal.TEN_KILLS_IN_A_ROW: "Killing Frenzy",
    GameResultsMedal.FIFTEEN_KILLS_IN_A_ROW: "Running Riot",
    GameResultsMedal.TWENTY_KILLS_IN_A_ROW: "Rampage",
    GameResultsMedal.TWENTY_FIVE_KILLS_IN_A_ROW: "Untouchable",
    GameResultsMedal.CTF_FLAG_GRAB: "Flag Grab",
    GameResultsMedal.CTF_FLAG_CARRIER_KILL: "Flag Carrier Kill",
    GameResultsMedal.CTF_FLAG_RETURNED: "Flag Returned",
    GameResultsMedal.CTF_BOMB_PLANTED: "Bomb Planted",
    GameResultsMedal.CTF_BOMB_CARRIER_KILL: "Bomb Carrier Kill",
    GameResultsMedal.CTF_BOMB_DEFUSED: "Bomb Defused",
}


def decode_medals(medals_by_type: int) -> List[str]:
    """
    Decode medals_earned_by_type bitmask into list of medal names.

    Args:
        medals_by_type: Bitmask from PCRPlayerStats.medals_earned_by_type

    Returns:
        List of medal name strings for each set bit
    """
    earned = []
    for medal in GameResultsMedal:
        if medals_by_type & (1 << medal.value):
            earned.append(MEDAL_NAMES.get(medal, medal.name))
    return earned


def detect_gametype_from_medals(players) -> Optional[str]:
    """
    Auto-detect gametype from medal bitmasks.

    Detection order:
    1. CTF medals (bits 18-20) -> "ctf"
    2. Assault medals (bits 21-23) -> "assault"
    3. Otherwise -> None (cannot distinguish Slayer, Oddball, KOTH,
       Juggernaut, Territories from medals/scores alone)

    Note: Time-format scores (e.g. "1:32") appear in Oddball, KOTH, AND
    Territories, so they cannot be used to identify a specific gametype.

    Returns:
        Gametype string or None if unable to determine
    """
    combined_medals = 0
    for p in players:
        combined_medals |= p.medals_earned_by_type

    CTF_BITS = (1 << 18) | (1 << 19) | (1 << 20)  # Flag Grab, Carrier Kill, Returned
    ASSAULT_BITS = (1 << 21) | (1 << 22) | (1 << 23)  # Bomb Planted, Carrier Kill, Defused

    if combined_medals & CTF_BITS:
        return "ctf"
    if combined_medals & ASSAULT_BITS:
        return "assault"

    return None


# =============================================================================
# Memory Addresses
# =============================================================================
#
# Address Types:
# 1. XBDM Direct - Work directly with Xemu's XBDM (verified working)
# 2. PCR (Post-game) - Only populated after game ends (from Yelo/OpenSauce)
# 3. HaloCaster Offsets - Need XBE base translation for XBDM use
#
# HaloCaster Address Calculation:
#   Xbox Virtual = XBE_BASE + HaloCaster_Offset
#   XBE_BASE = 0x8005C000
#   Physical = Xbox Virtual - 0x80000000
#
# Source: https://github.com/smx-smx/open-sauce/blob/master/OpenSauce/Halo2/Halo2_Xbox/Networking/Statistics.hpp
# Also: Yelo Carnage Stats.cs - "1.0 Address: 0x55CAF0"

# ADDRESSES, get_address, PCR_PLAYER_SIZE imported from addresses.py


# =============================================================================
# Data Structures
# =============================================================================

# Source: HaloCaster weapon_stat.cs weapon_list + friend's Executive Resolver data
@dataclass
class PCRPlayerStats:
    """
    Post-game Carnage Report stats (pcr_stat_player from OpenSauce).

    Source: https://github.com/smx-smx/open-sauce/blob/master/OpenSauce/Halo2/Halo2_Xbox/Networking/Statistics.hpp
    Also: Yelo Carnage Stats.cs

    Structure layout (total size: 0x114 = 276 bytes):
        0x00: PlayerName[16]     (wchar_t, 32 bytes)
        0x20: DisplayName[16]    (wchar_t, 32 bytes)
        0x40: ScoreString[16]    (wchar_t, 32 bytes)
        0x60: Kills              (int32)
        0x64: Deaths             (int32)
        0x68: Assists            (int32)
        0x6C: Suicides           (int32)
        0x70: Place              (int16)
        0x72: Team               (int16, team index: 0=Red, 1=Blue, etc.)
        0x74: Observer           (bool, 1 byte + 3 padding)
        0x78: Rank               (int16, Halo 2 skill rank 1-50)
        0x7A: RankVerified       (int16, whether rank is official)
        0x7C: MedalsEarned       (int32)
        0x80: MedalsEarnedByType (flags)
        0x84: TotalShots         (int32)
        0x88: ShotsHit           (int32)
        0x8C: HeadShots          (int32)
        0x90: Killed[16]         (int32 array - who you killed, by player index)
        0xD0: Unknown[4]         (16-byte structure)
        0xE0: PlaceString[16]    (wchar_t, 32 bytes)
        0x100: Unknown[3]        (12-byte structure)
        0x10C: GameTypeValue0    (int32 - varies by gametype)
        0x110: GameTypeValue1    (int32 - varies by gametype)

    GameType-specific values at 0x10C/0x110 (union, from OpenSauce):
        CTF:         FlagCarrierKills (Flag Saves), FlagGrabs (Flag Steals)
        Slayer:      AverageLife, MostKillsInARow (Best Spree)
        Oddball:     BallCarrierKills, KillsAsCarrier
        KOTH:        TotalControlTime, TimeOnHill
        Juggernaut:  JuggernautKills, KillsAsJuggernaut
        Territories: TerritoriesTaken, TerritoriesLost
        Assault:     BombGrabs, BombCarrierKills
    """
    player_name: str = ""
    display_name: str = ""
    score_string: str = ""
    kills: int = 0
    deaths: int = 0
    assists: int = 0
    suicides: int = 0
    place: int = 0
    team: int = 0               # Team index (0=Red, 1=Blue, 2=Yellow, etc.)
    observer: bool = False      # Is player spectating?
    rank: int = 0               # Halo 2 skill rank (1-50)
    rank_verified: int = 0      # Whether rank is official/verified
    place_string: str = ""
    medals_earned: int = 0
    medals_earned_by_type: int = 0  # Bitmask of medal types
    total_shots: int = 0
    shots_hit: int = 0
    headshots: int = 0
    killed: List[int] = field(default_factory=list)  # 16 entries: who you killed
    # Gametype-specific stats
    gametype_value0: int = 0
    gametype_value1: int = 0

    @classmethod
    def from_bytes(cls, data: bytes) -> 'PCRPlayerStats':
        """Parse PCR stats from raw memory bytes."""
        if len(data) < PCR_PLAYER_SIZE:
            raise ValueError(f"Need at least {PCR_PLAYER_SIZE} bytes")

        # Names at offsets 0x00, 0x20, and 0x40 (16 wide chars each)
        try:
            player_name = data[0:32].decode('utf-16-le').rstrip('\x00').strip()
            display_name = data[0x20:0x40].decode('utf-16-le').rstrip('\x00').strip()
            score_string = data[0x40:0x60].decode('utf-16-le').rstrip('\x00').strip()
        except:
            player_name = ""
            display_name = ""
            score_string = ""

        # Core stats at offset 0x60
        kills, deaths, assists, suicides = struct.unpack('<IIII', data[0x60:0x70])

        # Place at 0x70
        place = struct.unpack('<H', data[0x70:0x72])[0]

        # Team, observer, rank at 0x72-0x7B
        team = struct.unpack('<H', data[0x72:0x74])[0]
        observer = bool(data[0x74])
        rank = struct.unpack('<H', data[0x78:0x7A])[0]
        rank_verified = struct.unpack('<H', data[0x7A:0x7C])[0]

        # Medals at 0x7C and 0x80
        medals_earned = struct.unpack('<I', data[0x7C:0x80])[0]
        medals_by_type = struct.unpack('<I', data[0x80:0x84])[0]

        # Shots at 0x84
        total_shots, shots_hit, headshots = struct.unpack('<III', data[0x84:0x90])

        # Killed array at 0x90 (16 ints - who you killed)
        killed = list(struct.unpack('<16I', data[0x90:0xD0]))

        # Place string at 0xE0
        try:
            place_string = data[0xE0:0x100].decode('utf-16-le').rstrip('\x00')
        except:
            place_string = ""

        # Gametype-specific values at 0x10C
        gametype_value0 = struct.unpack('<I', data[0x10C:0x110])[0]
        gametype_value1 = struct.unpack('<I', data[0x110:0x114])[0]

        return cls(
            player_name=player_name,
            display_name=display_name,
            score_string=score_string,
            kills=kills,
            deaths=deaths,
            assists=assists,
            suicides=suicides,
            place=place,
            team=team,
            observer=observer,
            rank=rank,
            rank_verified=rank_verified,
            place_string=place_string,
            medals_earned=medals_earned,
            medals_earned_by_type=medals_by_type,
            total_shots=total_shots,
            shots_hit=shots_hit,
            headshots=headshots,
            killed=killed,
            gametype_value0=gametype_value0,
            gametype_value1=gametype_value1,
        )

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        accuracy = (self.shots_hit / self.total_shots * 100) if self.total_shots > 0 else 0

        return {
            "name": self.player_name,
            "display_name": self.display_name,
            "score_string": self.score_string,
            "place": self.place,
            "place_string": self.place_string,
            "team": self.team,
            "observer": self.observer,
            "rank": self.rank,
            "rank_verified": self.rank_verified,
            "kills": self.kills,
            "deaths": self.deaths,
            "assists": self.assists,
            "suicides": self.suicides,
            "kd_ratio": round(self.kills / max(self.deaths, 1), 2),
            "medals": {
                "total": self.medals_earned,
                "by_type": self.medals_earned_by_type,
            },
            "accuracy": {
                "total_shots": self.total_shots,
                "shots_hit": self.shots_hit,
                "headshots": self.headshots,
                "percentage": round(accuracy, 1),
            },
            "killed": self.killed,
            "gametype_values": [self.gametype_value0, self.gametype_value1],
        }

    def get_gametype_stats(self, gametype: str) -> dict:
        """
        Get gametype-specific interpretation of values at 0x10C/0x110.

        Args:
            gametype: One of "ctf", "slayer", "oddball", "koth", "juggernaut",
                      "territories", "assault"

        Returns:
            Dictionary with gametype-specific stat names and values

        Note: Label names match the in-game PGCR display column headers exactly.
        """
        mappings = {
            "ctf": {"Flag Saves": self.gametype_value0, "Flag Steals": self.gametype_value1},
            "slayer": {"Avg Life": self.gametype_value0, "Best Spree": self.gametype_value1},
            "oddball": {"Carrier Kills": self.gametype_value0, "Ball Kills": self.gametype_value1},
            "koth": {"Kings Killed": self.gametype_value0, "Kills From": self.gametype_value1},
            "juggernaut": {"Jugs Killed": self.gametype_value0, "Kills As Jug": self.gametype_value1},
            "territories": {"Terr. Taken": self.gametype_value0, "Terr. Lost": self.gametype_value1},
            "assault": {"Bomb Grabs": self.gametype_value0, "Bomber Kills": self.gametype_value1},
        }
        return mappings.get(gametype.lower(), {"value0": self.gametype_value0, "value1": self.gametype_value1})


# =============================================================================
# Helper Functions
# =============================================================================

def calculate_pcr_address(player_index: int) -> int:
    """
    Calculate memory address for player's PCR (Post-game Carnage Report) stats.

    This is the primary stats structure for Halo 2.
    Address: 0x55CAF0 + (player_index * 0x114)

    Args:
        player_index: Player slot (0-15)

    Returns:
        Xbox virtual memory address
    """
    base = get_address("pcr_stats")
    return base + (player_index * PCR_PLAYER_SIZE)


# PGCR Display constants
#
# The PGCR Display structure at 0x56B900 has a 0x90-byte header followed by
# pcr_stat_player records at stride 0x114 (same layout as PCR at 0x55CAF0).
# This means PCRPlayerStats.from_bytes() works directly on the player data!
#
# Structure:
#   0x56B900: 0x90 bytes of header
#     +0x84: gametype enum (int32) — same values as GameType IntEnum
#     +0x88: unknown (possibly map/scenario tag datum)
#   0x56B990: Player 0 (0x114 bytes, same as pcr_stat_player)
#   0x56BAA4: Player 1
#   0x56BBB8: Player 2
#   ...
# PGCR Display, team data, and breakpoint constants imported from addresses.py


def _parse_score_string(s: str) -> int:
    """Parse a PGCR score string into an integer value.

    Handles plain integers ("3"), time formats ("1:51", ":32", "2:00"),
    and returns 0 for empty/unparseable strings.
    Time strings are converted to total seconds.
    """
    s = s.strip()
    if not s:
        return 0
    # Time format: "M:SS" or ":SS"
    if ':' in s:
        parts = s.split(':')
        try:
            minutes = int(parts[0]) if parts[0] else 0
            seconds = int(parts[1]) if len(parts) > 1 and parts[1] else 0
            return minutes * 60 + seconds
        except (ValueError, IndexError):
            return 0
    # Plain integer
    try:
        return int(s)
    except ValueError:
        return 0


@dataclass
class TeamStats:
    """
    Post-game team statistics.

    Available at two locations (same 0x84-byte stride, same field layout):
    - PCR: 0x55DC30 (after 16 PCR player records) — EMPTY on docker-bridged-xemu
    - PGCR Display: 0x56CAD0 (after 16 PGCR player records) — PRIMARY source

    Layout per team (verified via hex dump on PGCR Display, Feb 2026):
        0x00: Team name (wchar_t[32], 64 bytes UTF-16LE)
        0x40: Score string (UTF-16LE, e.g. "3", "2:00", ":32")
        0x60: Team place (int16, 0-indexed)
        0x62: Team identity index (int16) — maps to H2 team colors
        0x64: Place string (UTF-16LE, e.g. "1st", "2nd")
    """
    name: str = ""
    score: int = 0
    score_string: str = ""
    place: int = 0
    place_string: str = ""
    team_id: int = -1
    index: int = 0

    @classmethod
    def from_bytes(cls, data: bytes, index: int = 0) -> 'TeamStats':
        """Parse TeamStats from raw memory bytes."""
        if len(data) < TEAM_DATA_STRIDE:
            raise ValueError(f"Need at least {TEAM_DATA_STRIDE} bytes, got {len(data)}")
        try:
            name = data[0:64].decode('utf-16-le').rstrip('\x00')
        except (UnicodeDecodeError, ValueError):
            name = ""
        # Score at 0x40 is a UTF-16LE display string (e.g. "3", "2:00", ":32"),
        # NOT an int32. Parse as string and convert to int when possible.
        try:
            score_string = data[0x40:0x60].decode('utf-16-le').rstrip('\x00').strip()
        except (UnicodeDecodeError, ValueError):
            score_string = ""
        score = _parse_score_string(score_string)
        place = struct.unpack('<h', data[0x60:0x62])[0]
        team_id = struct.unpack('<h', data[0x62:0x64])[0]
        try:
            place_string = data[0x64:0x84].decode('utf-16-le').rstrip('\x00')
        except (UnicodeDecodeError, ValueError):
            place_string = ""
        return cls(name=name, score=score, score_string=score_string,
                   place=place, place_string=place_string,
                   team_id=team_id, index=index)

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        result = {
            "index": self.index,
            "name": self.name,
            "score": self.score,
            "score_string": self.score_string,
            "place": self.place,
            "team_id": self.team_id,
        }
        if self.place_string:
            result["place_string"] = self.place_string
        return result


def calculate_pgcr_display_team_address(team_index: int) -> int:
    """
    Calculate memory address for team data in PGCR Display area.

    Located at 0x56CAD0 (immediately after 16 PGCR player records).
    This is the PRIMARY source — PCR team data at 0x55DC30 is empty on
    docker-bridged-xemu.

    Args:
        team_index: Team slot (0-7)

    Returns:
        Xbox memory address for the team record
    """
    return PGCR_DISPLAY_TEAM_BASE + (team_index * TEAM_DATA_STRIDE)


def calculate_team_data_address(team_index: int) -> int:
    """
    Calculate memory address for PCR team data (fallback).

    Args:
        team_index: Team slot (0-7)

    Returns:
        Xbox memory address for the team record
    """
    return TEAM_DATA_BASE + (team_index * TEAM_DATA_STRIDE)


def calculate_pgcr_display_address(player_index: int) -> int:
    """
    Calculate memory address for player's PGCR display stats.

    The PGCR Display at 0x56B900 has a 0x90-byte header, then standard
    pcr_stat_player records at 0x114 stride starting at 0x56B990.
    Only populated during the post-game carnage report screen.

    Args:
        player_index: Player slot (0-15)

    Returns:
        Xbox memory address for the player record
    """
    return PGCR_DISPLAY_BASE + (player_index * PGCR_DISPLAY_SIZE)
