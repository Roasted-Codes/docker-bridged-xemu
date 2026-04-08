# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

StatsBorg is a Halo 2 Xbox statistics tracking system. It reads post-game carnage report (PGCR) data from emulated Xbox memory (Xemu) via XBDM or QMP protocols, stores stats in SQLite, and serves a web UI with leaderboards and player analytics.

**No external dependencies** — uses Python standard library only (socket, struct, json, sqlite3, threading, http.server).

## Run Commands

```bash
# Read live stats via XBDM (port 731)
python halo2_stats.py --host 172.20.0.51

# Watch mode — auto-save on game completion
python halo2_stats.py --host 172.20.0.51 --watch

# Read via QMP (QEMU Machine Protocol)
python halo2_stats.py --host 172.20.0.10 --qmp 4444

# Start web server (initializes DB, auto-imports history, serves UI)
python pgcr_server.py 8080

# Test XBDM connectivity
python xbdm_client.py 172.20.0.51

# Test QMP connectivity
python qmp_client.py localhost 4444
```

## Architecture

```
Xbox Memory (Xemu)
       │
       ├── XBDM (port 731) ──► xbdm_client.py
       └── QMP  (port 4444) ──► qmp_client.py
                                      │
                    addresses.py ◄─── addresses.json (memory offsets)
                    halo2_structs.py  (binary struct parsing, enums)
                    halo2_stats.py    (high-level stats reader, CLI)
                                      │
                              data/history/*.json  (game snapshots)
                                      │
                              database.py  (SQLite import/query)
                                      │
                              pgcr_server.py  (HTTP API, port 8080)
                              pgcr_viewer.html (SPA frontend)
                              medals/*.gif
```

## Key Module Responsibilities

- **addresses.json / addresses.py** — Centralized Xbox memory addresses and struct layouts. `addresses.py` loads the JSON at import time and exposes addresses as module-level variables.
- **halo2_structs.py** — Binary struct definitions (`PCRPlayerStats` at 0x114 bytes, `TeamStats` at 0x84 bytes), game enums (`GameType`, `GameTeam`, `GameResultsMedal`), and parsers (`from_bytes()`, `decode_medals()`).
- **xbdm_client.py** — XBDM protocol client (TCP port 731). Rate-limited memory reads (50ms default) to prevent Xemu crashes. Also provides breakpoint API and notification listener.
- **qmp_client.py** — QMP protocol client (TCP port 4444). Handles VA-to-PA translation for user-space reads. Drop-in replacement for XBDMClient.
- **halo2_stats.py** — Main stats reader. Reads player/team data from memory, validates against garbage, detects gametypes, computes MD5 fingerprints for deduplication, saves JSON snapshots to `data/history/`.
- **database.py** — SQLite backend with thread-local connections. Schema: `games`, `players`, `teams` tables. Provides aggregate queries (career stats, leaderboards, PvP, player profiles).
- **pgcr_server.py** — HTTP server with REST API (`/api/games`, `/api/players`, `/api/leaderboard/{stat}`, `/api/pvp`). Auto-imports new history JSONs every 5 seconds.
- **pgcr_viewer.html** — Single-page app with game browser, player profiles, leaderboards, medal displays.

## Key Memory Addresses

- PCR Player base: `0x55CAF0` (16 slots × 0x114 bytes)
- PGCR Display base: `0x56B900` (header 0x90 bytes, then player/team data)
- PGCR Display teams: `0x56CAD0` (primary source for team data)
- Gametype (discovered): `0x52ED24`
- Variant name (physical): `0x036295F4` (UTF-16LE, QMP `_read_physical` only)
- Map content path (physical): `0x03629550` (ASCII, format `t:\$C\<title_id>\<map_name>`)
- Gametype byte (physical): `0x03629634` (variant_name + 0x40, single byte enum)

## Data Flow

1. Stats reader polls Xbox memory via XBDM/QMP
2. Binary data parsed into `PCRPlayerStats`/`TeamStats` structs
3. Game snapshots saved as timestamped JSON in `data/history/`
4. `pgcr_server.py` imports JSONs into SQLite (`data/statsborg.db`) with fingerprint deduplication
5. Web UI queries REST API for display

## Game Snapshot Schema (v3)

JSON files in `data/history/` contain: `schema_version`, `timestamp`, `fingerprint`, `source`, `gametype`, `gametype_id`, `player_count`, `map`, `variant`, `players[]` (with kills/deaths/assists/medals/accuracy/gametype_stats), and `teams[]`.
