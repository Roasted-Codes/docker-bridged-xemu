# HaloCaster vs StatsBorg Struct Comparison

## Summary
HaloCaster reads **extensive gametype-specific stats** that StatsBorg is currently **NOT capturing** from the PCR/PGCR Display structures. These fields exist in the same `PCRPlayerStats` 0x114-byte struct at offsets 0x10C-0x110 (gametype values), but HaloCaster sources them from a different, larger structure (`GAME_STATS_OFFSET = 0x35ADF02`, which does NOT work via QMP on our setup).

---

## What StatsBorg Currently Captures
From `halo2_structs.py`, `PCRPlayerStats` class:

### Core Stats (✓ We have these)
- **Kills** (0x60)
- **Deaths** (0x64)
- **Assists** (0x68)
- **Suicides** (0x6C)
- **Place** (0x70)
- **Team** (0x72)
- **Observer** (0x74)
- **Rank** (0x78)
- **Rank Verified** (0x7A)
- **Medals Earned** (0x7C) - total count
- **Medals Earned By Type** (0x80) - bitmask
- **Total Shots** (0x84)
- **Shots Hit** (0x88)
- **Headshots** (0x8C)
- **Killed Array** (0x90) - 16-int array
- **Gametype Value 0** (0x10C)
- **Gametype Value 1** (0x110)

---

## What HaloCaster Captures (from GAME_STATS structure)
From `HaloCasterLinux/halocaster/stats.py`, `GameStats` class:

### Core Stats (SAME as us)
- Kills (offset 0x00)
- Assists (offset 0x02)
- Deaths (offset 0x04)
- Betrayals (offset 0x06) ⚠️ **NOT IN PCRPlayerStats**
- Suicides (offset 0x08)
- Best Spree (offset 0x0A)
- Time Alive (offset 0x0C) ⚠️ **NOT IN PCRPlayerStats**

### Gametype-Specific Stats (HaloCaster reads from GAME_STATS at 0x35ADF02)

#### CTF (offsets 0x0E-0x16)
- `ctf_scores` (0x0E)
- `ctf_flag_steals` (0x10)
- `ctf_flag_saves` (0x12)
- `ctf_unknown` (0x14)

#### Assault (offsets 0x18-0x1E)
- `assault_score` (0x18)
- `assault_bomber_kills` (0x1A)
- `assault_bomb_grabbed` (0x1C)

#### Oddball (offsets 0x20-0x28)
- `oddball_score` (0x20) - int32
- `oddball_ball_kills` (0x24)
- `oddball_carried_kills` (0x26)

#### KOTH (offsets 0x28-0x2C)
- `koth_kills_as_king` (0x28)
- `koth_kings_killed` (0x2A)

#### Juggernaut (offsets 0x2C-0x32)
- `juggernauts_killed` (0x2C)
- `kills_as_juggernaut` (0x2E)
- `juggernaut_time` (0x30)

#### Territories (offsets 0x32-0x36)
- `territories_taken` (0x32)
- `territories_lost` (0x34)

---

## Comparison Table

| Field | StatsBorg PCRPlayerStats | HaloCaster GAME_STATS | Offset in GAME_STATS | Status |
|-------|--------------------------|----------------------|----------------------|--------|
| Kills | ✓ (0x60) | ✓ (0x00) | 0x00 | Same field |
| Assists | ✓ (0x68) | ✓ (0x02) | 0x02 | Same field |
| Deaths | ✓ (0x64) | ✓ (0x04) | 0x04 | Same field |
| **Betrayals** | ✗ | ✓ | 0x06 | **MISSING** |
| Suicides | ✓ (0x6C) | ✓ (0x08) | 0x08 | Same field |
| **Best Spree** | ✗ | ✓ | 0x0A | **MISSING** |
| **Time Alive** | ✗ | ✓ | 0x0C | **MISSING** |
| CTF Scores | ✓ (as gametype_value0) | ✓ | 0x0E | Indirect |
| CTF Flag Steals | ✓ (as gametype_value1) | ✓ | 0x10 | Indirect |
| CTF Flag Saves | ✓ (as gametype_value0) | ✓ | 0x12 | Indirect |
| Oddball/KOTH/Jug stats | ✓ (as gametype_value0/1) | ✓ (detailed) | 0x20+ | Indirect |
| Territories | ✓ (as gametype_value0/1) | ✓ (detailed) | 0x32-0x36 | Indirect |

---

## Key Findings

### ✓ We CAN Get These from PGCR Display
The fields HaloCaster reads at offsets 0x0E-0x36 **should theoretically exist in the GAME_STATS structure** (at Xbox virt 0x8039ADF02, but this does NOT work via QMP on our docker-bridged-xemu setup — it reads as all zeros).

However, the **gametype-specific values at 0x10C-0x110 in PCRPlayerStats** are what we're reading now, and they contain the same data, just in a different format (consolidated into two int32 values instead of separate fields).

### ✗ We're MISSING These from PCRPlayerStats
Three basic stats that HaloCaster reads but we DON'T:
1. **Betrayals** — friendly fire kills
2. **Best Spree** — longest kill streak
3. **Time Alive** — seconds alive in-game

These would require us to either:
- **Find equivalent fields in PCRPlayerStats** (they might be in the "Unknown" padding areas at 0xD0 or 0x100-0x10C)
- **Or, wait for HaloCaster Linux implementation to confirm they're not available in post-game structures**

### ⚠️ Data Source Mismatch
- **StatsBorg uses**: `PCRPlayerStats` from **PGCR Display** (0x56B900) or **PCR** (0x55CAF0)
  - These are POST-GAME structures, read after the game ends
  - We have gametype values compressed into 2 fields at 0x10C-0x110

- **HaloCaster uses**: `GAME_STATS` from **live memory** (0x35ADF02)
  - This is an IN-GAME structure, updated in real-time
  - It has detailed gametype-specific fields (0x0E-0x36)
  - This address DOES NOT work via QMP on our setup

---

## Recommendation

### Option 1: Leave as-is (RECOMMENDED)
StatsBorg is designed to read **post-game stats only** (via PGCR Display/PCR). The gametype-specific stats we're capturing (as `gametype_value0` and `gametype_value1`) are sufficient for the use case. We just interpret them based on the gametype ID.

**Pros:**
- Works reliably via QMP
- Matches the PGCR Display structure we've verified
- Handles all 7 gametypes with correct addressing

**Cons:**
- Missing betrayals, best spree, time alive (these may not be populated in post-game structures)
- Gametype stats require interpretation logic in `get_gametype_stats()`

### Option 2: Research if Betrayals/Spree/Time Alive exist in PCRPlayerStats
Check if these fields are hidden in the "Unknown" padding areas of `PCRPlayerStats`:
- `0xD0-0xE0` (16 bytes, currently unused)
- `0x100-0x10C` (12 bytes, currently unused)

**Pros:**
- Would give us more complete post-game data
- No need to rely on HaloCaster's live-game structure

**Cons:**
- Requires memory scanning and verification
- May not be populated at all

### Option 3: Support both structures (Complex)
Extend StatsBorg to read both:
- PGCR Display `gametype_value0/1` for primary stats
- (If ever working) Extended stats from another address

**Pros:**
- Maximum data completeness

**Cons:**
- Complex, error-prone, HaloCaster addresses don't work via QMP
- Not worth the effort for post-game-only use case

---

## Verdict

**The missing fields (betrayals, best spree, time alive) are likely IN-GAME stats only, not populated in post-game PGCR/PCR structures.** HaloCaster reads them from a live-game structure (`GAME_STATS = 0x35ADF02`) which makes sense — at game end, these stats are no longer being updated.

**StatsBorg is correct to focus on PGCR Display**, which is the canonical source for post-game reporting. Our `gametype_value0` and `gametype_value1` approach is valid and matches the struct layout.

---

## Files to Update (if we decide to add research)
- `research/scan_missing_stats.py` — Search for betrayals/spree/time_alive in padding areas
- `halo2_structs.py` — Add new fields if found
- `halo2_stats.py` — Update display logic if new stats found
