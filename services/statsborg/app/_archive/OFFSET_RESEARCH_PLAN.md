# StatsBorg Offset Research Plan

## Goal
Match or exceed HaloCaster's post-game stat coverage. HaloCaster gets fields we don't have
(betrayals, best_spree, total_time_alive, per-medal counts) by reading from a second live-game
memory region we haven't mapped yet. This plan finds those addresses reliably.

---

## What We Already Have (Don't Touch)

StatsBorg reads the full 0x114-byte PGCR Display struct correctly:

| Field | Offset | Notes |
|-------|--------|-------|
| player_name | 0x00 | UTF-16LE[16] |
| display_name | 0x20 | UTF-16LE[16] — HaloCaster skips this |
| score_string | 0x40 | UTF-16LE[16] |
| kills | 0x60 | int32 |
| deaths | 0x64 | int32 |
| assists | 0x68 | int32 |
| suicides | 0x6C | int32 |
| place | 0x70 | int16 — HaloCaster skips this |
| team | 0x72 | int16 |
| observer | 0x74 | bool |
| rank | 0x78 | int16 |
| rank_verified | 0x7A | int16 — HaloCaster reads this WRONG (0x7C off-by-2 bug) |
| medals_earned | 0x7C | int32 — HaloCaster reads this WRONG (0x7E misaligned) |
| medals_earned_by_type | 0x80 | int32 bitmask |
| total_shots | 0x84 | int32 |
| shots_hit | 0x88 | int32 |
| headshots | 0x8C | int32 |
| killed[16] | 0x90 | int32[16] — per-opponent kill matrix |
| **UNKNOWN[4]** | **0xD0** | **4 × int32 — UNEXPLORED** |
| place_string | 0xE0 | UTF-16LE[16] |
| **UNKNOWN[3]** | **0x100** | **2 × int32 + 1 byte + pad — UNEXPLORED** |
| gametype_value0 | 0x10C | int32 — HaloCaster skips this |
| gametype_value1 | 0x110 | int32 — HaloCaster skips this |

**StatsBorg is actually AHEAD of HaloCaster's post_game_report.cs in field coverage.**
The gap is: HaloCaster reads a SECOND live-game struct to get betrayals/best_spree/time_alive.

---

## What's Missing and Why

### Fields in HaloCaster `game_stats` not in PGCR

| Field | HaloCaster offset | Accessible via QMP? |
|-------|-------------------|---------------------|
| betrayals | game_stats+0x06 | NOT YET — need to find in user-space |
| best_spree | game_stats+0x0A | NOT YET |
| total_time_alive | game_stats+0x0C | NOT YET |
| per-medal counts (24 types) | medal_stats base | NOT YET |

HaloCaster reads these from kernel VA gap addresses (0x35ADF02 etc.) which work via Windows
ReadProcessMemory but NOT via QMP `xp`. The data MUST live somewhere in user-space memory
too — we just haven't found it yet.

---

## Research Approach

### Track A: Mine the Unknown Bytes (Fastest — Start Here)

The PGCR struct has 28 bytes we never parse (0xD0–0xDF and 0x100–0x10B). These could
contain betrayals, best_spree, or time_alive. We'd know if we looked.

**Tool needed:** `research/dump_pgcr_full.py`
- Read raw 0x114 bytes for each player from 0x56B990
- Print full annotated hex dump with known fields labeled
- Highlight unknown regions
- Usage: Run after a game where you committed betrayals or had a kill spree
- Then read the hex values and compare to the in-game scoreboard screenshot

**Interactive workflow:**
1. Play a game, note your betrayals and best spree from the in-game score
2. Run `python research/dump_pgcr_full.py --host 172.20.0.10 --qmp 4444`
3. Examine the unknown bytes — if 0xD4 = your betrayal count, we're done

### Track B: Memory Snapshot After Every Game (Async — Works With Streaming Sessions)

For sessions where you can't do live scans:
- Use QMP `pmemsave` to save full 64MB RAM snapshot after each game ends
- Snapshots saved alongside the PGCR JSON in `history/`
- Later, when reviewing Twitch VOD for actual scoreboard values, run comparison scripts

**Tool needed:** Enhanced `--watch` mode + `research/compare_snapshots.py`

`--watch` changes:
- After detecting game end (PGCR populated), trigger a `pmemsave` BEFORE reading PGCR
- Save to `history/YYYY-MM-DD_HH-MM-SS_<fingerprint>_ram.bin` (64MB per game)
- Optional flag: `--save-ram` to enable (default off — 64MB per game is large)

`research/compare_snapshots.py`:
- Takes a ram snapshot + known values (from Twitch review)
- Searches the full 64MB for those values and reports candidate addresses
- Usage: `python research/compare_snapshots.py ram.bin --find-int 3 --label "betrayals" --find-int 7 --label "best_spree"`
- Cross-references against already-known addresses to narrow candidates

### Track C: HaloCaster Bridge (Definitive Solution)

HaloCaster's memory reads work (Windows ReadProcessMemory). We want to know WHERE in physical
Xbox RAM those values live, so we can read the same data via QMP.

**The insight:** HaloCaster reads a value (e.g., betrayals=3). We take a QMP RAM snapshot at
the same time. We search the 64MB snapshot for the value 3 in context with other known values
(kills, deaths, etc.). That gives us the physical address.

**Tool needed:** `research/halocaster_bridge.py` — a Python server that:
1. Receives a "game snapshot" payload from a HaloCaster addon via HTTP or named pipe:
   - All player stats at game end (betrayals, best_spree, time_alive, per-medal counts)
2. Immediately triggers a QMP `pmemsave` of full RAM
3. Searches the snapshot for those exact values in proximity to known PGCR addresses
4. Reports candidate physical addresses → Xbox VAs for each field

**HaloCaster addon needed:** A small C# addition to WhatTheFuck that, at post_game trigger,
POSTs the game_stats + medal_stats values to localhost:PORT before the game transitions.

This is a one-time calibration tool. Once we have the addresses, they go into `addresses.json`
and we never need the bridge again.

---

## Implementation Phases

### Phase 1: dump_pgcr_full.py (Do First — 30 min, could solve everything)
Write `research/dump_pgcr_full.py`:
- Full hex dump of PGCR Display 0x114-byte struct for all valid players
- Annotate known fields, highlight 0xD0–0xDF and 0x100–0x10B gaps
- Works via `--qmp` flag

**Feedback needed from user:**
- Play a game, note your betrayals count and best spree from in-game HUD
- Run the dump script at the PGCR screen
- Report what values appear in the unknown byte regions

### Phase 2: RAM Snapshot Support in watch mode
Add `--save-ram` flag to `halo2_stats.py --watch`:
- After game-end detection, before reading PGCR: `qmp_client.save_ram(filename)`
- Add `QMPClient.save_ram(path)` using `pmemsave` command (already understand protocol)
- Save to `history/` alongside JSON

Add `research/compare_snapshots.py`:
- Value-search tool for RAM binary dumps
- Finds all locations of a given int16/int32 value in 64MB
- Cross-references against known addresses to filter noise

### Phase 3: HaloCaster Bridge (After Phase 1/2 confirm the addresses)
If Phases 1/2 don't find the addresses:
1. Write `research/halocaster_bridge.py` HTTP listener
2. Write C# addon for HaloCaster WhatTheFuck to POST game_stats at game end
3. Correlate HaloCaster values → QMP snapshot → physical addresses
4. Add confirmed addresses to `addresses.json`

### Phase 4: Parse New Fields (After addresses confirmed)
Once we know the offsets (whether from PGCR unknown bytes or new addresses):
- Add fields to `PCRPlayerStats.from_bytes()` in `halo2_structs.py`
- Add to `to_dict()` and `build_snapshot()` in `halo2_stats.py`
- Bump `schema_version` to 4
- Update `addresses.json` with new confirmed offsets
- Update `CLAUDE.md`

---

## File Locations

| File | Status | Purpose |
|------|--------|---------|
| `halo2_structs.py` | Existing | Add new fields after Phase 1/2/3 |
| `halo2_stats.py` | Existing | Add `--save-ram`, serialize new fields |
| `qmp_client.py` | Existing | Add `save_ram()` using `pmemsave` |
| `addresses.json` | Existing | Add newly discovered offsets |
| `research/dump_pgcr_full.py` | **NEW Phase 1** | Annotated hex dump of PGCR struct |
| `research/compare_snapshots.py` | **NEW Phase 2** | Value search in 64MB RAM dumps |
| `research/halocaster_bridge.py` | **NEW Phase 3** | HTTP bridge + correlation tool |
| HaloCaster C# addon | **NEW Phase 3** | POST game_stats at game end |

---

## Key Insight: Why This Order

The unknown bytes (0xD0–0xDF, 0x100–0x10B) are the fastest path.
If betrayals/best_spree/time_alive are sitting in those 28 bytes, we just parse them.
No live scanning, no HaloCaster bridge, no address hunting.
Only if they're NOT there do we escalate to the more complex approaches.

---

## HaloCaster Reference (Do NOT Use These Addresses Directly)
These are host VA offsets that work via ReadProcessMemory but NOT via QMP:
- game_stats: 0x35ADF02 (stride 0x36A/player)
- medal_stats: 0x35ADF4E
- weapon_stats: 0x35ADFE0
- session_players: 0x35AD344
- variant_info: 0x35AD0EC (+0x40 = gametype byte)
- life_cycle: 0x35E4F04 (in_lobby=1, starting=2, in_game=3, post_game=4)
- post_game_report: 0x363A990 (same 0x114 struct, different base from our 0x56B900)
