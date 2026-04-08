"""
Canonical address loader for Halo 2 Xbox memory constants.

Reads addresses.json once at import time and exposes all constants as
module-level variables used by halo2_structs.py and halo2_stats.py.

Zero dependencies on other project modules (leaf module).
"""
import json
import os

# ---------------------------------------------------------------------------
# Load addresses.json
# ---------------------------------------------------------------------------

_JSON_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "addresses.json")

with open(_JSON_PATH) as _f:
    _DATA = json.load(_f)


def _parse_hex(value):
    """Convert '0x...' strings to int, pass ints through unchanged."""
    if isinstance(value, str) and value.startswith("0x"):
        return int(value, 16)
    return value


# ---------------------------------------------------------------------------
# Post-game addresses (halo2_structs.py constants)
# ---------------------------------------------------------------------------

_post = _DATA["post_game"]
_pgcr = _post["pgcr_display"]
_pcr = _post["pcr_fallback"]
_bp = _post["breakpoint"]
_gt_addrs = _post["gametype_addresses"]
_misc = _post["misc"]

# ADDRESSES dict — same keys and values as the old halo2_structs.ADDRESSES
ADDRESSES = {
    "gametype_enum": _parse_hex(_gt_addrs["xbox7887"]["address"]),
    "pcr_stats": _parse_hex(_pcr["player_base"]),
    "team_data": _parse_hex(_pcr["team_base"]),
    "profile_data": _parse_hex(_misc["profile_data"]),
    "str_kills": _parse_hex(_misc["str_kills"]),
    "str_deaths": _parse_hex(_misc["str_deaths"]),
}


def get_address(name: str) -> int:
    """Get Xbox virtual memory address by name."""
    return ADDRESSES.get(name, 0)


# PCR struct size
PCR_PLAYER_SIZE = _parse_hex(_pcr["player_stride"])

# PGCR Display constants
PGCR_DISPLAY_HEADER = _parse_hex(_pgcr["header"])
PGCR_DISPLAY_HEADER_SIZE = _parse_hex(_pgcr["header_size"])
PGCR_DISPLAY_GAMETYPE_OFFSET = _parse_hex(_pgcr["gametype_offset"])
PGCR_DISPLAY_GAMETYPE_ADDR = _parse_hex(_pgcr["gametype_addr"])
PGCR_DISPLAY_BASE = _parse_hex(_pgcr["player_base"])
PGCR_DISPLAY_SIZE = _parse_hex(_pgcr["player_stride"])

# Team data constants
TEAM_DATA_BASE = _parse_hex(_pcr["team_base"])
PGCR_DISPLAY_TEAM_BASE = _parse_hex(_pgcr["team_base"])
TEAM_DATA_STRIDE = _parse_hex(_pgcr["team_stride"])
MAX_TEAMS = _DATA["sizing"]["max_teams"]

# Breakpoint
PGCR_BREAKPOINT_ADDR = _parse_hex(_bp["pgcr_clear"])

# ---------------------------------------------------------------------------
# Discovered addresses and sizing
# ---------------------------------------------------------------------------

# Empirically discovered addresses
_disc = _DATA["discovered"]
DISCOVERED_ADDRESSES = {k: _parse_hex(v) for k, v in _disc.items()
                        if not k.startswith("_")}

MAX_PLAYERS = _DATA["sizing"]["max_players"]
