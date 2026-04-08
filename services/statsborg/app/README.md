# StatsBorg — Halo 2 Post-Game Stats Reader

Cross-platform Python tool that reads Halo 2 multiplayer post-game statistics from Xbox/Xemu via XBDM or QMP. Linux-compatible alternative to Windows-only HaloCaster.

**Stats captured:** Kills, deaths, assists, suicides, K/D ratio, accuracy (shots/hits/headshots), medals, placement, team data, and gametype-specific stats across all game modes (Slayer, CTF, Oddball, KOTH, Juggernaut, Territories, Assault).

## Requirements

- Python 3.7+ (no pip dependencies for core tool)
- One of:
  - Xbox with XBDM enabled (debug kit or modded console with CerbiosDebug)
  - Xemu with QMP enabled (launch with `-qmp tcp:0.0.0.0:4444,server,nowait`)

## Quick Start

### 1. Capture Stats

Run watch mode in the background during your session. It auto-detects game completions and saves stats after each match:

**QMP (Xemu) — primary method:**

```bash
python halo2_stats.py --host <XEMU_IP> --qmp 4444 --watch
```

Requires Xemu launched with `-qmp tcp:0.0.0.0:4444,server,nowait`.

**XBDM (Xbox/Xemu with CerbiosDebug):**

```bash
# Polling (checks every 3 seconds)
python halo2_stats.py --host <XBOX_IP> --watch

# Instant detection via breakpoint (no polling delay)
python halo2_stats.py --host <XBOX_IP> --watch --breakpoint
```

Each completed game is automatically deduplicated and saved as JSON to the `history/` directory.

### 2. View Your Stats

Start the built-in web viewer to browse your game history:

```bash
python pgcr_server.py
```

Open **http://localhost:8080** in your browser. The viewer reads all saved games from `history/` and displays them with scores, placements, and per-player breakdowns.

To use a different port: `python pgcr_server.py 9090`

## Where Stats Are Stored

All game data is saved to the `history/` directory as JSON files, one per game:

```
history/
  2026-02-18_22-31-58_cf561ec1.json
  2026-02-18_21-59-26_bc2c035c.json
  ...
```

Each file is named `<date>_<time>_<fingerprint>.json` and contains the full scoreboard: every player's stats, team data, and gametype. These files are consumed by the web viewer and the export scripts.

## Output Formats

```bash
# Default: rich scoreboard with accuracy, medals, gametype stats
python halo2_stats.py --host <IP> --save

# Simple K/D/A summary
python halo2_stats.py --host <IP> --simple

# PGCR tabular format (matches in-game screenshot layout)
python halo2_stats.py --host <IP> --pgcr

# JSON output (to stdout)
python halo2_stats.py --host <IP> --json

# JSON output to a specific file
python halo2_stats.py --host <IP> --json --output stats.json
```

## Additional Flags

| Flag | Description |
|------|-------------|
| `--port N` | XBDM port (default: 731) |
| `--poll N` | Poll every N seconds without watch mode (0 = single read) |
| `--watch-interval N` | Seconds between watch-mode polls (default: 3) |
| `--breakpoint`, `-b` | Use XBDM breakpoint for instant game-end detection instead of polling |
| `--history-dir DIR` | Directory for auto-saved games (default: history/) |
| `--pgcr-display` | Also read killed-by data from PGCR display (post-game screen only) |
| `--timeout N` | Connection timeout in seconds (default: 5) |
| `--slow` | 200ms read delay instead of 50ms (XBDM only, safer for unstable connections) |
| `--save-ram` | Save full 64MB RAM snapshot at game end (QMP only, large files) |
| `--verbose` | Debug logging |

## Testing Your Connection

```bash
# Test XBDM
python xbdm_client.py <XBOX_IP>

# Test QMP
python qmp_client.py <XEMU_IP> 4444
```

## Export (Optional)

Export scripts require additional dependencies:

```bash
pip install -r exports/requirements.txt
```

```bash
# PostgreSQL
python exports/db_export.py --init-schema
python exports/db_export.py --import-history

# Excel
python exports/xlsx_export.py --history-dir history/ -o halo2_stats.xlsx

# Per-game Excel sheets (Bungie-style)
python exports/xlsx_export.py --per-game --style bungie -o exports/bungie/
```

## Project Structure

```
halo2_stats.py        Main CLI tool
xbdm_client.py        XBDM protocol client
qmp_client.py         QMP protocol client
halo2_structs.py      Data structures and struct parsing
addresses.json        Memory address reference
pgcr_server.py        Web viewer server
pgcr_viewer.html      Browser-based game history viewer
history/              Saved game data (JSON, one file per game)
exports/              PostgreSQL and Excel export scripts
```

## Credits

- Memory structures from [OpenSauce](https://github.com/OpenSauce-Halo-CE/OpenSauce) (`Networking/Statistics.hpp`)
- Research informed by [HaloCaster](https://github.com/I2aMpAnT/HaloCaster) and Yelo Carnage
