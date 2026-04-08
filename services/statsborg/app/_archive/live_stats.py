"""
Live Stats Module — CURRENTLY NON-FUNCTIONAL VIA XBDM
=====================================================

WHAT THIS FILE IS:
    This module contains code for reading Halo 2 statistics in REAL-TIME
    during gameplay (not just post-game). It includes structs for live
    kill/death tracking, per-weapon stats, detailed medal counts, game
    variant info, and player session properties.

    This code was extracted from halo2_structs.py and halo2_stats.py during
    the Feb 2026 refactoring to keep the main tool focused on what works.

WHY IT DOESN'T WORK YET:
    The Xbox has 64MB of physical RAM. To read memory via XBDM (the Xbox
    Debug Monitor), you need a "virtual address" — a label the Xbox uses
    to look up the physical data. The Xbox has a directory (page table)
    that maps labels to physical locations.

    The live stats data sits at physical addresses around 54MB into RAM.
    The corresponding virtual address labels (0x835xxxxx range) are in a
    section of the directory that's "torn out" — XBDM says those pages
    are "not committed." The data physically exists, but XBDM can't
    reach it through those labels.

    The post-game stats (PGCR Display at 0x56B900) work because they
    use virtual addresses in the "user-space" range (below 0x80000000),
    where the directory is intact.

    Specifically, the kernel VA gap is at 0x83145000-0x83AC4000. The
    translated live-stats addresses (e.g., game_stats = 0x83609F02)
    land squarely in this gap.

HOW TO MAKE THIS WORK (FUTURE):
    Option A: Implement QMP (QEMU Machine Protocol) to read Xemu's
              memory directly as a flat 64MB buffer, bypassing the
              virtual address system entirely. This is how HaloCaster
              does it on Windows via ReadProcessMemory.

    Option B: Find user-space virtual addresses for the same data.
              The game engine clearly accesses this data (it shows stats
              on screen), so it must have valid addresses internally. We
              could scan XBDM-accessible memory for recognizable patterns
              (e.g., a player's current kill count during gameplay) to
              find where this data lives in user-space.

    Option C: Use a different XBDM implementation that can traverse
              the "uncommitted" kernel pages differently.

    QMP could also serve as a research tool: read at HaloCaster's known
    offsets in flat RAM, then scan XBDM-accessible pages for the same
    data pattern to find the user-space VA for permanent XBDM access.

WHAT DATA THIS MODULE WOULD PROVIDE (once working):
    - Real-time kills/deaths/assists during gameplay (not just post-game)
    - Per-weapon stat breakdowns (kills, shots, headshots for each of 41 weapons)
    - Detailed medal COUNTS (how many doubles, triples, etc. — not just a bitmask)
    - Game variant info (map name, gametype variant name)
    - Game lifecycle state (in lobby, in game, post-game)
    - Player session properties (team, colors, character, skill rank)

STRUCT REFERENCE:
    - GameStats: 0x36 bytes per player, stride 0x36A in the full array
    - WeaponStat: 0x10 bytes per weapon (41 weapons), part of 0x36A stride
    - MedalStats: 0x30 bytes per player (24 medal types x 2 bytes each)
    - PlayerProperties: 0xA4 bytes per player (name, team, colors, rank)
    - VariantInfo: 0x131 bytes (variant name, game type, scenario path)

ADDRESS MAPPING (HaloCaster → Xbox):
    HaloCaster reads from Xemu's Windows process memory at offsets
    relative to host_base = Translate(0x80000000) + 0x5C000.

    To convert to Xbox addresses:
        physical_addr = 0x5C000 + halocaster_offset
        xbox_kernel_va = 0x80000000 + physical_addr

    Example: game_stats offset 0x35ADF02
        physical = 0x5C000 + 0x35ADF02 = 0x360DF02 (~54MB)
        kernel VA = 0x80000000 + 0x360DF02 = 0x8360DF02
        This is in the gap (0x83145000-0x83AC4000) → XBDM can't read it

    The gap represents physical addresses ~19MB-59MB that the Xbox kernel
    doesn't map with standard page table entries. The data exists physically
    but has no virtual address that XBDM can use.

SOURCES:
    - HaloCaster: Form1.cs resolve_addresses(), game_stats.cs, weapon_stat.cs,
      medal_stats.cs, variant_details.cs, real_time_player_stats.cs
    - Yelo Carnage: Stats.cs, Program.Watch.cs
    - OpenSauce: Networking/Statistics.hpp
"""

import struct
from dataclasses import dataclass, field
from typing import Dict, List, Optional
from enum import IntEnum
from datetime import datetime

from addresses import (
    XBE_BASE, PHYSICAL_BASE,
    HALOC_OFFSETS, LIVE_ADDRESSES,
    YELO_ADDRESSES, DISCOVERED_ADDRESSES,
    GAME_STATS_SIZE, GAME_STATS_STRUCT,
    SESSION_PLAYER_SIZE, WEAPON_STAT_SIZE,
    MEDAL_STATS_STRUCT, WEAPON_COUNT, LOBBY_PLAYER_SIZE,
    get_live_address, get_haloc_address,
    haloc_to_xbox_virtual, xbox_virtual_to_physical,
)


# =============================================================================
# Enums (used by live stats structs)
# =============================================================================

class PlayerColor(IntEnum):
    """Player armor color options in Halo 2."""
    WHITE = 0
    STEEL = 1
    RED = 2
    ORANGE = 3
    GOLD = 4
    OLIVE = 5
    GREEN = 6
    SAGE = 7
    CYAN = 8
    TEAL = 9
    COBALT = 10
    BLUE = 11
    VIOLET = 12
    PURPLE = 13
    PINK = 14
    CRIMSON = 15
    BROWN = 16
    TAN = 17


class CharacterType(IntEnum):
    """Player character model in Halo 2."""
    MASTERCHIEF = 0
    DERVISH = 1
    SPARTAN = 2
    ELITE = 3


class Handicap(IntEnum):
    """Player handicap level."""
    NONE = 0
    MINOR = 1
    MODERATE = 2
    SEVERE = 3


class GameResultsStatistic(IntEnum):
    """
    Statistics tracked in game results.

    Source: Yelo Carnage Stats.cs
    These are enum indices for the game results globals structure,
    which tracks aggregate stats per player across games.
    """
    GAMES_PLAYED = 0
    GAMES_QUIT = 1
    GAMES_DISCONNECTED = 2
    GAMES_COMPLETED = 3
    GAMES_WON = 4
    GAMES_TIED = 5
    ROUNDS_WON = 6
    KILLS = 7
    ASSISTS = 8
    DEATHS = 9
    BETRAYALS = 10
    SUICIDES = 11
    MOST_KILLS_IN_A_ROW = 12
    SECONDS_ALIVE = 13
    CTF_FLAG_SCORES = 14
    CTF_FLAG_GRABS = 15
    CTF_FLAG_CARRIER_KILLS = 16
    CTF_FLAG_RETURNS = 17
    CTF_BOMB_SCORES = 18
    CTF_BOMB_PLANTS = 19
    CTF_BOMB_CARRIER_KILLS = 20
    CTF_BOMB_GRABS = 21
    CTF_BOMB_RETURNS = 22
    ODDBALL_TIME_WITH_BALL = 23
    ODDBALL_UNUSED = 24
    ODDBALL_KILLS_AS_CARRIER = 25
    ODDBALL_BALL_CARRIER_KILLS = 26
    KOTH_TIME_ON_HILL = 27
    KOTH_TOTAL_CONTROL_TIME = 28
    KOTH_NUMBER_OF_CONTROLS = 29  # unused
    KOTH_LONGEST_CONTROL_TIME = 30  # unused
    RACE_LAPS = 31  # unused
    RACE_TOTAL_LAP_TIME = 32  # unused
    RACE_FASTEST_LAP_TIME = 33  # unused
    HEADHUNTER_HEADS_PICKED_UP = 34  # unused
    HEADHUNTER_HEADS_DEPOSITED = 35  # unused
    HEADHUNTER_NUMBER_OF_DEPOSITS = 36  # unused
    HEADHUNTER_LARGEST_DEPOSIT = 37  # unused
    JUGGERNAUT_KILLS = 38
    JUGGERNAUT_KILLS_AS_JUGGERNAUT = 39
    JUGGERNAUT_TOTAL_CONTROL_TIME = 40
    JUGGERNAUT_NUMBER_OF_CONTROLS = 41  # unused
    JUGGERNAUT_LONGEST_CONTROL_TIME = 42  # unused
    TERRITORIES_TAKEN = 43
    TERRITORIES_LOST = 44


class LifeCycle(IntEnum):
    """
    Game lifecycle states.

    Source: HaloCaster life_cycle enum
    Read from: LIVE_ADDRESSES["life_cycle"] (0x83640F04 — in kernel VA gap)
    """
    NONE = 0
    PRE_GAME = 1
    IN_LOBBY = 2
    IN_GAME = 3
    POST_GAME = 4


# =============================================================================
# Address Constants
# =============================================================================

# Address constants, struct sizes, and helper functions imported from addresses.py


# =============================================================================
# Weapon Names (41 weapons, indices 0-40)
# Source: HaloCaster weapon_stat.cs
# =============================================================================

WEAPON_NAMES = [
    "Guardians",            # 0
    "Falling Damage",       # 1
    "Collision Damage",     # 2
    "Generic Melee",        # 3
    "Generic Explosion",    # 4
    "Magnum",               # 5
    "Plasma Pistol",        # 6
    "Needler",              # 7
    "SMG",                  # 8
    "Plasma Rifle",         # 9
    "Battle Rifle",         # 10
    "Carbine",              # 11
    "Shotgun",              # 12
    "Sniper Rifle",         # 13
    "Beam Rifle",           # 14
    "Brute Plasma Rifle",   # 15
    "Rocket Launcher",      # 16
    "Fuel Rod",             # 17
    "Brute Shot",           # 18
    "Disintegrator",        # 19
    "Sentinel Beam",        # 20
    "Sentinel RPG",         # 21
    "Energy Sword",         # 22
    "Frag Grenade",         # 23
    "Plasma Grenade",       # 24
    "Flag Melee",           # 25
    "Bomb Melee",           # 26
    "Ball Melee",           # 27
    "Human Turret",         # 28
    "Plasma Turret",        # 29
    "Banshee",              # 30
    "Ghost",                # 31
    "Mongoose",             # 32
    "Scorpion",             # 33
    "Spectre Driver",       # 34
    "Spectre Gunner",       # 35
    "Warthog Driver",       # 36
    "Warthog Gunner",       # 37
    "Wraith",               # 38
    "Tank",                 # 39
    "Bomb Explosion",       # 40
]


# =============================================================================
# Address Helper Functions
# =============================================================================

# haloc_to_xbox_virtual, xbox_virtual_to_physical, get_haloc_address,
# get_live_address imported from addresses.py


def calculate_live_stats_address(player_index: int) -> int:
    """
    Calculate memory address for player's LIVE game stats during gameplay.

    Address: LIVE_ADDRESSES["game_stats"] + (player_index * GAME_STATS_SIZE)
    For players 5-15, stats are in a separate overflow area.

    NOTE: These addresses are in the kernel VA gap and cannot be read via XBDM.
    """
    if player_index <= 4:
        return LIVE_ADDRESSES["game_stats"] + (player_index * GAME_STATS_SIZE)
    else:
        return LIVE_ADDRESSES["game_results_extra"] + ((player_index - 5) * GAME_STATS_SIZE)


def calculate_session_player_address(player_index: int) -> int:
    """
    Calculate memory address for player's session properties (name, team, etc.)

    NOTE: These addresses are in the kernel VA gap and cannot be read via XBDM.
    """
    return LIVE_ADDRESSES["session_players"] + (player_index * SESSION_PLAYER_SIZE)


def calculate_medal_stats_address(player_index: int) -> int:
    """
    Calculate memory address for player's medal stats during gameplay.

    NOTE: These addresses are in the kernel VA gap and cannot be read via XBDM.
    """
    if player_index <= 4:
        return LIVE_ADDRESSES["medal_stats"] + (player_index * GAME_STATS_SIZE)
    else:
        return LIVE_ADDRESSES["game_results_extra"] + 0x4C + ((player_index - 5) * GAME_STATS_SIZE)


def calculate_weapon_stats_address(player_index: int, weapon_index: int = 0) -> int:
    """
    Calculate memory address for player's weapon stats during gameplay.

    NOTE: These addresses are in the kernel VA gap and cannot be read via XBDM.
    """
    weapon_offset = weapon_index * WEAPON_STAT_SIZE
    if player_index <= 4:
        return LIVE_ADDRESSES["weapon_stats"] + (player_index * GAME_STATS_SIZE) + weapon_offset
    else:
        return LIVE_ADDRESSES["game_results_extra"] + 0xDE + ((player_index - 5) * GAME_STATS_SIZE) + weapon_offset


# =============================================================================
# Data Structures
# =============================================================================

# Import GameTeam from the main structs module (shared between live and post-game)
from halo2_structs import GameTeam


@dataclass
class GameStats:
    """
    Live in-game statistics for a player.

    Source: HaloCaster game_stats.cs
    Total struct size: 54 bytes (0x36)
    Stride in memory: 0x36A (858 bytes) — contains game_stats + weapon_stats + medal_stats

    This struct tracks real-time kills, deaths, and gametype-specific stats
    during active gameplay. It updates continuously as the game progresses.

    To read this, you need access to:
        LIVE_ADDRESSES["game_stats"] + (player_index * 0x36A)
    which is at Xbox kernel VA ~0x83609F02 (in the inaccessible gap).
    """
    kills: int = 0
    assists: int = 0
    deaths: int = 0
    betrayals: int = 0
    suicides: int = 0
    best_spree: int = 0
    total_time_alive: int = 0
    # CTF
    ctf_scores: int = 0
    ctf_flag_steals: int = 0
    ctf_flag_saves: int = 0
    ctf_unknown: int = 0
    # Assault
    assault_suicides: int = 0
    assault_scores: int = 0
    assault_bomber_kills: int = 0
    assault_bomb_grabbed: int = 0
    assault_bomb_unknown: int = 0
    # Oddball
    oddball_score: int = 0  # uint32
    oddball_ball_kills: int = 0
    oddball_carried_kills: int = 0
    # King of the Hill
    koth_kills_as_king: int = 0
    koth_kings_killed: int = 0
    # Juggernaut
    juggernauts_killed: int = 0
    kills_as_juggernaut: int = 0
    juggernaut_time: int = 0
    # Territories
    territories_taken: int = 0
    territories_lost: int = 0

    @classmethod
    def from_bytes(cls, data: bytes) -> 'GameStats':
        """Parse GameStats from raw memory bytes."""
        if len(data) < 54:
            raise ValueError(f"Need at least 54 bytes, got {len(data)}")
        # Format: 16 ushorts, 1 uint32 (oddball_score), 9 more ushorts
        fields = struct.unpack('<16H I 9H', data[:54])
        return cls(
            kills=fields[0], assists=fields[1], deaths=fields[2],
            betrayals=fields[3], suicides=fields[4], best_spree=fields[5],
            total_time_alive=fields[6],
            ctf_scores=fields[7], ctf_flag_steals=fields[8],
            ctf_flag_saves=fields[9], ctf_unknown=fields[10],
            assault_suicides=fields[11], assault_scores=fields[12],
            assault_bomber_kills=fields[13], assault_bomb_grabbed=fields[14],
            assault_bomb_unknown=fields[15],
            oddball_score=fields[16],  # uint32 at index 16
            oddball_ball_kills=fields[17], oddball_carried_kills=fields[18],
            koth_kills_as_king=fields[19], koth_kings_killed=fields[20],
            juggernauts_killed=fields[21], kills_as_juggernaut=fields[22],
            juggernaut_time=fields[23],
            territories_taken=fields[24], territories_lost=fields[25],
        )

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return {
            "kills": self.kills, "assists": self.assists, "deaths": self.deaths,
            "betrayals": self.betrayals, "suicides": self.suicides,
            "best_spree": self.best_spree, "total_time_alive": self.total_time_alive,
            "ctf": {"scores": self.ctf_scores, "flag_steals": self.ctf_flag_steals,
                    "flag_saves": self.ctf_flag_saves},
            "assault": {"suicides": self.assault_suicides, "scores": self.assault_scores,
                       "bomber_kills": self.assault_bomber_kills,
                       "bomb_grabbed": self.assault_bomb_grabbed},
            "oddball": {"score": self.oddball_score, "ball_kills": self.oddball_ball_kills,
                       "carried_kills": self.oddball_carried_kills},
            "koth": {"kills_as_king": self.koth_kills_as_king,
                    "kings_killed": self.koth_kings_killed},
            "juggernaut": {"juggernauts_killed": self.juggernauts_killed,
                          "kills_as_juggernaut": self.kills_as_juggernaut,
                          "time": self.juggernaut_time},
            "territories": {"taken": self.territories_taken, "lost": self.territories_lost},
        }


@dataclass
class WeaponStat:
    """
    Per-weapon statistics for a single player.

    Source: HaloCaster weapon_stat.cs
    Size: 0x10 (16 bytes) per weapon, but only 14 bytes contain data.
    There are 41 weapons (indices 0-40, see WEAPON_NAMES list above).

    To read weapon N for player P:
        addr = weapon_stats_base + (P * 0x36A) + (N * 0x10)
    """
    kills: int = 0
    deaths: int = 0
    suicide: int = 0
    shots_fired: int = 0
    shots_hit: int = 0
    head_shots: int = 0

    @classmethod
    def from_bytes(cls, data: bytes) -> 'WeaponStat':
        """Parse WeaponStat from 16 bytes of raw memory."""
        if len(data) < 14:
            raise ValueError(f"Need at least 14 bytes, got {len(data)}")
        # Layout: kills(2), deaths(2), gap(2), suicide(2), shots_fired(2), shots_hit(2), head_shots(2)
        kills, deaths, _, suicide, shots_fired, shots_hit, head_shots = \
            struct.unpack('<7H', data[:14])
        return cls(kills=kills, deaths=deaths, suicide=suicide,
                   shots_fired=shots_fired, shots_hit=shots_hit, head_shots=head_shots)

    def to_dict(self) -> dict:
        return {"kills": self.kills, "deaths": self.deaths, "suicide": self.suicide,
                "shots_fired": self.shots_fired, "shots_hit": self.shots_hit,
                "head_shots": self.head_shots}


@dataclass
class MedalStats:
    """
    Per-player medal counts (how many of each medal type).

    Source: HaloCaster medal_stats.cs
    Total size: 48 bytes (0x30), 24 unsigned shorts (one count per medal type).

    This gives you COUNTS (e.g., "3 double kills") unlike the post-game
    bitmask which only tells you "got at least one double kill."

    To read for player P:
        Players 0-4: medal_stats_base + (P * 0x36A)
        Players 5+: game_results_extra + 0x4C + ((P-5) * 0x36A)
    """
    double_kill: int = 0
    triple_kill: int = 0
    killtacular: int = 0
    kill_frenzy: int = 0
    killtrocity: int = 0
    killamanjaro: int = 0
    sniper_kill: int = 0
    road_kill: int = 0       # Splatter
    bone_cracker: int = 0    # Beat Down
    assassin: int = 0        # Stealth Kill
    vehicle_destroyed: int = 0
    car_jacking: int = 0     # Boarded Vehicle
    stick_it: int = 0        # Grenade Stick
    killing_spree: int = 0   # 5 kills
    running_riot: int = 0    # 10 kills
    rampage: int = 0         # 15 kills
    berserker: int = 0       # 20 kills
    over_kill: int = 0       # 25 kills
    flag_taken: int = 0
    flag_carrier_kill: int = 0
    flag_returned: int = 0
    bomb_planted: int = 0
    bomb_carrier_kill: int = 0
    bomb_returned: int = 0

    @classmethod
    def from_bytes(cls, data: bytes) -> 'MedalStats':
        """Parse MedalStats from raw memory bytes."""
        if len(data) < 48:
            raise ValueError(f"Need at least 48 bytes, got {len(data)}")
        fields = struct.unpack('<24H', data[:48])
        return cls(
            double_kill=fields[0], triple_kill=fields[1],
            killtacular=fields[2], kill_frenzy=fields[3],
            killtrocity=fields[4], killamanjaro=fields[5],
            sniper_kill=fields[6], road_kill=fields[7],
            bone_cracker=fields[8], assassin=fields[9],
            vehicle_destroyed=fields[10], car_jacking=fields[11],
            stick_it=fields[12], killing_spree=fields[13],
            running_riot=fields[14], rampage=fields[15],
            berserker=fields[16], over_kill=fields[17],
            flag_taken=fields[18], flag_carrier_kill=fields[19],
            flag_returned=fields[20], bomb_planted=fields[21],
            bomb_carrier_kill=fields[22], bomb_returned=fields[23],
        )

    def to_dict(self) -> dict:
        return {k: v for k, v in self.__dict__.items() if v > 0}

    def total(self) -> int:
        return sum(self.__dict__.values())


@dataclass
class VariantInfo:
    """
    Current game variant info (map name, gametype name, scenario path).

    Source: HaloCaster variant_details.cs
    Total size: 0x131 (305 bytes)

    This tells you WHAT map and gametype variant is being played.
    The scenario_path contains the internal map name which can be
    mapped to display names (e.g., "beavercreek" → "Beaver Creek").

    To read: LIVE_ADDRESSES["variant_info"] (0x836090EC — in gap)
    """
    variant_name: str = ""
    game_type: int = 0
    scenario_path: str = ""

    GAME_TYPE_NAMES = {
        0: "None", 1: "CTF", 2: "Slayer", 3: "Oddball",
        4: "KOTH", 7: "Juggernaut", 8: "Territories",
        9: "Assault", 11: "VIP",
    }

    # Map internal names → display names
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

    @classmethod
    def from_bytes(cls, data: bytes) -> 'VariantInfo':
        """Parse VariantInfo from raw memory bytes."""
        if len(data) < 0x131:
            raise ValueError(f"Need at least 305 bytes, got {len(data)}")
        try:
            variant_name = data[0:32].decode('utf-16-le').rstrip('\x00')
        except:
            variant_name = ""
        game_type = data[0x40]
        try:
            scenario_path = data[0x130:0x230].split(b'\x00')[0].decode('ascii')
        except:
            scenario_path = ""
        return cls(variant_name=variant_name, game_type=game_type, scenario_path=scenario_path)

    @property
    def game_type_name(self) -> str:
        return self.GAME_TYPE_NAMES.get(self.game_type, f"Unknown({self.game_type})")

    @property
    def map_name(self) -> str:
        """Get display name for the current map from scenario path."""
        if not self.scenario_path:
            return "Unknown"
        # Scenario path is like "scenarios\\multi\\beavercreek\\beavercreek"
        parts = self.scenario_path.replace('\\', '/').split('/')
        internal = parts[-1] if parts else ""
        return self.MAP_NAMES.get(internal, internal)

    def to_dict(self) -> dict:
        return {
            "variant_name": self.variant_name,
            "game_type": self.game_type,
            "game_type_name": self.game_type_name,
            "scenario_path": self.scenario_path,
            "map_name": self.map_name,
        }


@dataclass
class PlayerProperties:
    """
    Player session properties (name, team, appearance, skill).

    Source: HaloCaster real_time_player_stats.cs
    Total size: 164 bytes (0xA4)

    This contains the player's current session data: name, team assignment,
    armor colors, character model, and skill ranking. It's separate from
    the game stats (kills/deaths) — this is "who they are" not "how they're doing."

    To read for player P:
        LIVE_ADDRESSES["session_players"] + (P * 0xA4)
    """
    player_name: str = ""
    team: GameTeam = GameTeam.NEUTRAL
    primary_color: PlayerColor = PlayerColor.WHITE
    secondary_color: PlayerColor = PlayerColor.WHITE
    tertiary_color: PlayerColor = PlayerColor.WHITE
    quaternary_color: PlayerColor = PlayerColor.WHITE
    character_type: CharacterType = CharacterType.SPARTAN
    handicap: Handicap = Handicap.NONE
    displayed_skill: int = 0
    overall_skill: int = 0
    is_griefer: bool = False

    @classmethod
    def from_bytes(cls, data: bytes) -> 'PlayerProperties':
        """Parse PlayerProperties from raw memory bytes."""
        if len(data) < 0xA4:
            raise ValueError(f"Need at least 164 bytes, got {len(data)}")
        name_bytes = data[0:32]
        try:
            name = name_bytes.decode('utf-16-le').rstrip('\x00')
        except:
            name = ""
        # s_player_profile_traits at offset 0x40
        profile_offset = 0x40
        primary = data[profile_offset] if profile_offset < len(data) else 0
        secondary = data[profile_offset + 1] if profile_offset + 1 < len(data) else 0
        tertiary = data[profile_offset + 2] if profile_offset + 2 < len(data) else 0
        quaternary = data[profile_offset + 3] if profile_offset + 3 < len(data) else 0
        char_type = data[profile_offset + 4] if profile_offset + 4 < len(data) else 0
        # Team and skill at 0x7C+ (after profile_traits + clan_name + clan_identifiers)
        team = data[0x7C] if 0x7C < len(data) else 8
        handicap = data[0x7D] if 0x7D < len(data) else 0
        displayed_skill = data[0x7E] if 0x7E < len(data) else 0
        overall_skill = data[0x7F] if 0x7F < len(data) else 0
        is_griefer = data[0x80] if 0x80 < len(data) else 0
        return cls(
            player_name=name,
            team=GameTeam(min(team, 8)),
            primary_color=PlayerColor(min(primary, 17)),
            secondary_color=PlayerColor(min(secondary, 17)),
            tertiary_color=PlayerColor(min(tertiary, 17)),
            quaternary_color=PlayerColor(min(quaternary, 17)),
            character_type=CharacterType(min(char_type, 3)),
            handicap=Handicap(min(handicap, 3)),
            displayed_skill=displayed_skill,
            overall_skill=overall_skill,
            is_griefer=bool(is_griefer),
        )

    def to_dict(self) -> dict:
        return {
            "name": self.player_name,
            "team": self.team.name.lower(),
            "character": self.character_type.name.lower(),
            "colors": {
                "primary": self.primary_color.name.lower(),
                "secondary": self.secondary_color.name.lower(),
                "tertiary": self.tertiary_color.name.lower(),
                "quaternary": self.quaternary_color.name.lower(),
            },
            "handicap": self.handicap.name.lower(),
            "skill": {"displayed": self.displayed_skill, "overall": self.overall_skill},
            "is_griefer": self.is_griefer,
        }


@dataclass
class PGCRDisplayStats:
    """
    Post-Game Carnage Report DISPLAY structure (empirically discovered).

    Located at 0x56B900 (different from PCR at 0x55CAF0!).
    This was an early discovery during research — we later found that
    PCRPlayerStats.from_bytes() works directly on PGCR Display data
    because the player records use the same 0x114-byte layout.

    This class is kept for reference but is NOT used in production.
    The main tool uses PCRPlayerStats for both PCR and PGCR Display reads.
    """
    player_name: str = ""
    score_string: str = ""
    place: int = 0
    place_string: str = ""
    kills: int = 0
    deaths: int = 0
    assists: int = 0
    suicides: int = 0
    total_shots: int = 0
    shots_hit: int = 0
    headshots: int = 0
    killed_by: List[int] = field(default_factory=list)

    @classmethod
    def from_bytes(cls, data: bytes) -> 'PGCRDisplayStats':
        """Parse PGCR display stats from raw memory bytes."""
        if len(data) < 0x200:
            raise ValueError(f"Need at least 512 bytes, got {len(data)}")
        place = struct.unpack('<I', data[0x84:0x88])[0]
        try:
            player_name = data[0x90:0xB0].decode('utf-16-le').rstrip('\x00')
        except:
            player_name = ""
        try:
            score_string = data[0xCC:0xEC].decode('utf-16-le').rstrip('\x00')
        except:
            score_string = ""
        kills = struct.unpack('<I', data[0xF0:0xF4])[0]
        deaths = struct.unpack('<I', data[0xF4:0xF8])[0]
        assists = struct.unpack('<I', data[0xF8:0xFC])[0]
        suicides = struct.unpack('<I', data[0xFC:0x100])[0]
        total_shots = struct.unpack('<I', data[0x114:0x118])[0]
        shots_hit = struct.unpack('<I', data[0x118:0x11C])[0]
        headshots = struct.unpack('<I', data[0x11C:0x120])[0]
        killed_by = list(struct.unpack('<16I', data[0x120:0x160]))
        try:
            place_string = data[0x168:0x188].decode('utf-16-le').rstrip('\x00')
        except:
            place_string = ""
        return cls(player_name=player_name, score_string=score_string, place=place,
                   place_string=place_string, kills=kills, deaths=deaths,
                   assists=assists, suicides=suicides, total_shots=total_shots,
                   shots_hit=shots_hit, headshots=headshots, killed_by=killed_by)

    def to_dict(self) -> dict:
        accuracy = (self.shots_hit / self.total_shots * 100) if self.total_shots > 0 else 0
        return {
            "name": self.player_name, "score_string": self.score_string,
            "place": self.place, "place_string": self.place_string,
            "kills": self.kills, "deaths": self.deaths,
            "assists": self.assists, "suicides": self.suicides,
            "accuracy": {"total_shots": self.total_shots, "shots_hit": self.shots_hit,
                        "headshots": self.headshots, "percentage": round(accuracy, 1)},
            "killed_by": self.killed_by,
        }


@dataclass
class PlayerStats:
    """Combined player statistics (properties + game stats) for live reading."""
    index: int
    properties: PlayerProperties
    game_stats: GameStats
    address: int = 0

    def to_dict(self) -> dict:
        return {
            "index": self.index,
            "player": self.properties.to_dict(),
            "stats": self.game_stats.to_dict(),
            "_debug": {"address": f"0x{self.address:08X}"},
        }


# =============================================================================
# Live Stats Reader Functions
#
# These functions read live stats from XBDM. They require an XBDMClient
# instance passed as the first argument. Currently non-functional because
# the target addresses are in the kernel VA gap.
#
# To use these, you would need either:
#   1. QMP access to read flat physical memory
#   2. Discovery of user-space VAs for the same data
# =============================================================================

def read_life_cycle(client, verbose=False):
    """
    Read current game life cycle state.

    Args:
        client: XBDMClient instance
        verbose: Print debug info

    Returns:
        LifeCycle enum value, or None on error
    """
    addr = get_live_address("life_cycle")
    if verbose:
        print(f"Reading life_cycle from 0x{addr:08X}")
    data = client.read_memory(addr, 4)
    if not data or len(data) < 4:
        return None
    value = struct.unpack('<I', data)[0]
    try:
        return LifeCycle(value)
    except ValueError:
        return LifeCycle.NONE


def read_live_player_stats(client, player_index, verbose=False):
    """
    Read LIVE stats for a single player during gameplay.

    Args:
        client: XBDMClient instance
        player_index: Player slot (0-15)
        verbose: Print debug info

    Returns:
        GameStats if successful, None on error
    """
    addr = calculate_live_stats_address(player_index)
    if verbose:
        print(f"Reading live stats for player {player_index} from 0x{addr:08X}")
    data = client.read_memory(addr, GAME_STATS_STRUCT)
    if not data:
        return None
    try:
        return GameStats.from_bytes(data)
    except Exception:
        return None


def read_session_player(client, player_index, verbose=False):
    """
    Read player session properties (name, team, etc.)

    Args:
        client: XBDMClient instance
        player_index: Player slot (0-15)
        verbose: Print debug info

    Returns:
        PlayerProperties if successful, None on error
    """
    addr = calculate_session_player_address(player_index)
    if verbose:
        print(f"Reading session player {player_index} from 0x{addr:08X}")
    data = client.read_memory(addr, SESSION_PLAYER_SIZE)
    if not data:
        return None
    try:
        return PlayerProperties.from_bytes(data)
    except Exception:
        return None


def read_all_live_players(client, verbose=False):
    """Read live stats for all players with valid names."""
    players = []
    for i in range(16):
        props = read_session_player(client, i, verbose)
        if props and props.player_name.strip():
            stats = read_live_player_stats(client, i, verbose)
            if stats:
                players.append({
                    "index": i,
                    "name": props.player_name,
                    "team": props.team.name.lower(),
                    "kills": stats.kills,
                    "deaths": stats.deaths,
                    "assists": stats.assists,
                    "betrayals": stats.betrayals,
                    "suicides": stats.suicides,
                })
    return players


def get_live_snapshot(client, verbose=False):
    """
    Get a complete snapshot of current LIVE game state.

    Returns a dictionary ready for JSON serialization.
    """
    life_cycle = read_life_cycle(client, verbose)
    players = read_all_live_players(client, verbose)
    return {
        "timestamp": datetime.now().isoformat(),
        "life_cycle": life_cycle.name if life_cycle else "UNKNOWN",
        "player_count": len(players),
        "players": players,
    }


# =============================================================================
# Display Functions
# =============================================================================

def format_live_player_summary(player):
    """Format a single player's live stats as a readable line."""
    name = player["name"][:16].ljust(16)
    k, d, a = player["kills"], player["deaths"], player["assists"]
    kd = k / max(d, 1)
    return f"{name} K:{k:3d} D:{d:3d} A:{a:3d} K/D:{kd:.2f}"


def print_live_scoreboard(players, life_cycle):
    """Print a formatted live scoreboard to console."""
    print("\n" + "=" * 60)
    print(f" HALO 2 LIVE STATS - {life_cycle}")
    print("=" * 60)
    if not players:
        print(" No players found in game.")
    else:
        sorted_players = sorted(players, key=lambda p: p["kills"], reverse=True)
        for i, player in enumerate(sorted_players, 1):
            print(f" {i:2d}. {format_live_player_summary(player)}")
    print("=" * 60)
    print()
