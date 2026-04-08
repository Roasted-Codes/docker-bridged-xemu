#!/usr/bin/env bash
# StatsBorg One-Click Launcher
# Starts xemu (with QMP on port 4444), halo2_stats.py --watch, and pgcr_server.py
set -u -o pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

QMP_PORT=4444
WEB_PORT=8080
LOG_DIR="$SCRIPT_DIR/logs"
DATA_DIR="$SCRIPT_DIR/data"
HISTORY_DIR="$DATA_DIR/history"
PID_FILE="$SCRIPT_DIR/.statsborg.pids"

# Process tracking (unset until launched)
XEMU_PID=""
XEMU_MANAGED=false
XEMU_PREEXISTING=false
STATS_PID=""
SERVER_PID=""

# CLI flags
KILL_XEMU_ON_EXIT=false
NO_BROWSER=false

# ── Color helpers ──────────────────────────────────────────────────────
if [[ -t 1 ]]; then
    CLR_GREEN='\033[0;32m'
    CLR_YELLOW='\033[1;33m'
    CLR_RED='\033[0;31m'
    CLR_CYAN='\033[0;36m'
    CLR_BOLD='\033[1m'
    CLR_RESET='\033[0m'
else
    CLR_GREEN='' CLR_YELLOW='' CLR_RED='' CLR_CYAN='' CLR_BOLD='' CLR_RESET=''
fi

info()  { echo -e "${CLR_GREEN}[INFO]${CLR_RESET} $*"; }
warn()  { echo -e "${CLR_YELLOW}[WARN]${CLR_RESET} $*"; }
error() { echo -e "${CLR_RED}[ERROR]${CLR_RESET} $*" >&2; }
step()  { echo -e "${CLR_CYAN}${CLR_BOLD}[$1]${CLR_RESET} $2"; }

# ── Cleanup handler ───────────────────────────────────────────────────
graceful_kill() {
    local pid="$1" name="$2"
    kill -INT "$pid" 2>/dev/null
    # Wait up to 5 seconds for graceful exit
    for _ in {1..10}; do
        kill -0 "$pid" 2>/dev/null || break
        sleep 0.5
    done
    # Force kill if still running
    if kill -0 "$pid" 2>/dev/null; then
        warn "$name (PID $pid) did not exit gracefully, sending SIGKILL..."
        kill -9 "$pid" 2>/dev/null
    fi
    wait "$pid" 2>/dev/null || true
    info "Stopped $name (PID $pid)"
}

cleanup() {
    local exit_code="${1:-0}"
    echo ""
    info "Shutting down StatsBorg..."

    if [[ -n "$SERVER_PID" ]] && kill -0 "$SERVER_PID" 2>/dev/null; then
        graceful_kill "$SERVER_PID" "web server"
    fi

    if [[ -n "$STATS_PID" ]] && kill -0 "$STATS_PID" 2>/dev/null; then
        graceful_kill "$STATS_PID" "stats watcher"
    fi

    if [[ -n "$XEMU_PID" ]] && [[ "$XEMU_MANAGED" == "true" ]]; then
        if kill -0 "$XEMU_PID" 2>/dev/null; then
            if [[ "$KILL_XEMU_ON_EXIT" == "true" ]]; then
                info "Stopping xemu (PID $XEMU_PID)..."
                kill "$XEMU_PID" 2>/dev/null
                wait "$XEMU_PID" 2>/dev/null || true
                info "xemu stopped."
            else
                info "xemu (PID $XEMU_PID) left running. Stop with: kill $XEMU_PID"
            fi
        fi
    fi

    rm -f "$PID_FILE"
    exit "$exit_code"
}

trap 'cleanup 0' INT TERM

# ── Port check helper ─────────────────────────────────────────────────
port_in_use() {
    ss -tln 2>/dev/null | awk -v p="$1" '$4 ~ ":"p"$" {found=1} END {exit !found}'
}

wait_for_port() {
    local port="$1" label="$2" timeout="${3:-30}"
    local elapsed=0
    while (( elapsed < timeout )); do
        if port_in_use "$port"; then
            info "$label port $port is ready"
            return 0
        fi
        # If we launched xemu, check it hasn't died
        if [[ -n "$XEMU_PID" ]] && ! kill -0 "$XEMU_PID" 2>/dev/null; then
            error "xemu exited unexpectedly. Check $LOG_DIR/xemu.log"
            cleanup 1
        fi
        sleep 1
        (( elapsed++ ))
    done
    error "$label port $port did not open after ${timeout}s"
    return 1
}

# ── Health check helper ───────────────────────────────────────────────
health_check() {
    local pid="$1" name="$2" logfile="$3" delay="${4:-2}"
    sleep "$delay"
    if ! kill -0 "$pid" 2>/dev/null; then
        error "$name (PID $pid) died on startup!"
        error "Last lines from $logfile:"
        tail -10 "$logfile" 2>/dev/null | while IFS= read -r line; do
            error "  $line"
        done
        return 1
    fi
    return 0
}

# ── Rotate a log file ─────────────────────────────────────────────────
rotate_log() {
    local logfile="$1"
    if [[ -f "$logfile" ]]; then
        mv "$logfile" "${logfile}.prev"
    fi
}

# ── Parse CLI arguments ───────────────────────────────────────────────
for arg in "$@"; do
    case "$arg" in
        --kill-xemu)  KILL_XEMU_ON_EXIT=true ;;
        --no-browser) NO_BROWSER=true ;;
        --help|-h)
            echo "Usage: $0 [--kill-xemu] [--no-browser]"
            echo ""
            echo "Options:"
            echo "  --kill-xemu   Also stop xemu when StatsBorg exits"
            echo "  --no-browser  Don't auto-open the web UI in a browser"
            echo "  --help, -h    Show this help message"
            exit 0 ;;
        *)
            error "Unknown option: $arg"
            echo "Usage: $0 [--kill-xemu] [--no-browser]"
            exit 1 ;;
    esac
done

# ══════════════════════════════════════════════════════════════════════
# STEP 1: Prerequisites
# ══════════════════════════════════════════════════════════════════════
step "1/6" "Checking prerequisites..."

if ! command -v xemu &>/dev/null; then
    error "xemu not found in PATH. Please install xemu first."
    exit 1
fi

if ! command -v python3 &>/dev/null; then
    error "python3 not found in PATH. Please install Python 3."
    exit 1
fi

mkdir -p "$HISTORY_DIR" "$LOG_DIR"
info "Prerequisites OK (xemu, python3, directories)"

# ══════════════════════════════════════════════════════════════════════
# STEP 2: Handle stale processes from a previous run
# ══════════════════════════════════════════════════════════════════════
step "2/6" "Checking for previous StatsBorg instances..."

if [[ -f "$PID_FILE" ]]; then
    warn "Found PID file from a previous run"
    # Source it in a subshell to avoid polluting our variables
    while IFS='=' read -r key val; do
        case "$key" in
            STATS_PID)
                if [[ -n "$val" ]] && kill -0 "$val" 2>/dev/null; then
                    info "Stopping leftover stats watcher (PID $val)..."
                    kill -INT "$val" 2>/dev/null || true
                fi
                ;;
            SERVER_PID)
                if [[ -n "$val" ]] && kill -0 "$val" 2>/dev/null; then
                    info "Stopping leftover web server (PID $val)..."
                    kill -INT "$val" 2>/dev/null || true
                fi
                ;;
        esac
    done < "$PID_FILE"
    rm -f "$PID_FILE"
    sleep 1
    info "Previous instances cleaned up"
else
    info "No stale instances found"
fi

# ══════════════════════════════════════════════════════════════════════
# STEP 3: Check ports
# ══════════════════════════════════════════════════════════════════════
step "3/6" "Checking ports..."

if port_in_use "$QMP_PORT"; then
    # Could be a pre-existing xemu — let the user keep it
    warn "QMP port $QMP_PORT is already in use (pre-existing xemu?)"
    info "Will use existing QMP connection instead of launching new xemu"
    XEMU_PREEXISTING=true
else
    info "QMP port $QMP_PORT is free"
fi

if port_in_use "$WEB_PORT"; then
    error "Web server port $WEB_PORT is already in use!"
    error "Stop the process using it, or change WEB_PORT at the top of this script."
    exit 1
fi
info "Web server port $WEB_PORT is free"

# ══════════════════════════════════════════════════════════════════════
# STEP 4: Launch xemu
# ══════════════════════════════════════════════════════════════════════
step "4/6" "Starting xemu..."

if [[ "$XEMU_PREEXISTING" == "true" ]]; then
    info "Skipping xemu launch (using existing instance on port $QMP_PORT)"
else
    rotate_log "$LOG_DIR/xemu.log"
    info "Launching xemu with QMP on 0.0.0.0:${QMP_PORT}..."
    xemu -qmp "tcp:0.0.0.0:${QMP_PORT},server,nowait" \
        >"$LOG_DIR/xemu.log" 2>&1 &
    XEMU_PID=$!
    XEMU_MANAGED=true
    info "xemu PID: $XEMU_PID (log: logs/xemu.log)"

    if ! wait_for_port "$QMP_PORT" "QMP" 30; then
        error "Failed to start xemu. Check $LOG_DIR/xemu.log for details."
        cleanup 1
    fi
fi

# ══════════════════════════════════════════════════════════════════════
# STEP 5: Launch Python services
# ══════════════════════════════════════════════════════════════════════
step "5/6" "Starting StatsBorg services..."

# Stats watcher
rotate_log "$LOG_DIR/halo2_stats.log"
info "Launching halo2_stats.py --watch (QMP mode)..."
python3 -u "$SCRIPT_DIR/halo2_stats.py" \
    --host localhost --qmp "$QMP_PORT" --watch \
    > >(tee -a "$LOG_DIR/halo2_stats.log") 2>&1 &
STATS_PID=$!
info "Stats watcher PID: $STATS_PID (log: logs/halo2_stats.log)"

# Web server
rotate_log "$LOG_DIR/pgcr_server.log"
info "Launching pgcr_server.py on port ${WEB_PORT}..."
python3 -u "$SCRIPT_DIR/pgcr_server.py" "$WEB_PORT" \
    >>"$LOG_DIR/pgcr_server.log" 2>&1 &
SERVER_PID=$!
info "Web server PID: $SERVER_PID (log: logs/pgcr_server.log)"

# Health checks
if ! health_check "$STATS_PID" "halo2_stats" "$LOG_DIR/halo2_stats.log" 2; then
    cleanup 1
fi

if ! health_check "$SERVER_PID" "pgcr_server" "$LOG_DIR/pgcr_server.log" 2; then
    cleanup 1
fi

if ! wait_for_port "$WEB_PORT" "Web server" 10; then
    error "Web server failed to bind port. Check $LOG_DIR/pgcr_server.log"
    cleanup 1
fi

# Write PID file for future runs
cat > "$PID_FILE" <<EOF
STATS_PID=$STATS_PID
SERVER_PID=$SERVER_PID
XEMU_PID=$XEMU_PID
XEMU_MANAGED=$XEMU_MANAGED
EOF

# Auto-open browser
if [[ "$NO_BROWSER" != "true" ]] && command -v xdg-open &>/dev/null; then
    info "Opening browser at http://localhost:${WEB_PORT}..."
    xdg-open "http://localhost:${WEB_PORT}" 2>/dev/null &
fi

# Wait for tunnel URL (best-effort, non-blocking)
TUNNEL_URL=""
for _ in {1..15}; do
    if [[ -f "$LOG_DIR/pgcr_server.log" ]]; then
        TUNNEL_URL=$(grep -o 'https://[a-z0-9-]*\.trycloudflare\.com' "$LOG_DIR/pgcr_server.log" 2>/dev/null | head -1)
        if [[ -n "$TUNNEL_URL" ]]; then
            break
        fi
    fi
    sleep 1
done

# ══════════════════════════════════════════════════════════════════════
# STEP 6: Running
# ══════════════════════════════════════════════════════════════════════
step "6/6" "StatsBorg is running!"
echo ""
echo -e "${CLR_BOLD}==========================================${CLR_RESET}"
echo -e "${CLR_BOLD} StatsBorg is running!${CLR_RESET}"
echo -e "${CLR_BOLD}==========================================${CLR_RESET}"
if [[ "$XEMU_PREEXISTING" == "true" ]]; then
    echo "  xemu:          pre-existing (port $QMP_PORT)"
else
    echo "  xemu:          PID $XEMU_PID (log: logs/xemu.log)"
fi
echo "  Stats watcher: PID $STATS_PID (log: logs/halo2_stats.log)"
echo "  Web server:    http://localhost:${WEB_PORT} (log: logs/pgcr_server.log)"
if [[ -n "$TUNNEL_URL" ]]; then
    echo -e "  Public URL:    ${CLR_GREEN}${TUNNEL_URL}${CLR_RESET}"
else
    echo "  Public URL:    (not available — cloudflared not found or slow to start)"
fi
echo ""
echo "  Press Ctrl+C to stop stats watcher and web server."
if [[ "$XEMU_MANAGED" == "true" ]]; then
    if [[ "$KILL_XEMU_ON_EXIT" == "true" ]]; then
        echo "  xemu will be stopped on exit (--kill-xemu)."
    else
        echo "  xemu will be left running."
    fi
fi
echo -e "${CLR_BOLD}==========================================${CLR_RESET}"
echo ""

# Monitor loop — exit if either Python process dies
while true; do
    if ! kill -0 "$STATS_PID" 2>/dev/null; then
        warn "Stats watcher exited unexpectedly. Check $LOG_DIR/halo2_stats.log"
        cleanup 1
    fi
    if ! kill -0 "$SERVER_PID" 2>/dev/null; then
        warn "Web server exited unexpectedly. Check $LOG_DIR/pgcr_server.log"
        cleanup 1
    fi
    sleep 3
done
