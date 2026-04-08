"""Serve the PGCR viewer with auto-discovery of history files.

Now uses SQLite database backend for efficient querying.

Usage: python pgcr_server.py [port]        (default: 8080)
"""
import glob
import json
import os
import shutil
import signal
import subprocess
import sys
import time
import threading
from collections import defaultdict
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
from database import (
    init_db, import_game, import_history_dir,
    get_all_games, get_game, get_all_players, get_player, get_leaderboard,
    get_pvp_stats
)

ROOT = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(ROOT, "data")
HISTORY_DIR = os.path.join(DATA_DIR, "history")
VIEWER_PATH = os.path.join(ROOT, "pgcr_viewer.html")
DB_PATH = os.path.join(DATA_DIR, "statsborg.db")

# File monitoring state
_known_files = set()
_import_lock = threading.Lock()

# SSE clients — list of wfile objects to push events to
_sse_clients = []
_sse_lock = threading.Lock()


def _notify_sse_clients(event_data):
    """Send an SSE event to all connected clients."""
    msg = f"data: {json.dumps(event_data)}\n\n"
    with _sse_lock:
        dead = []
        for wfile in _sse_clients:
            try:
                wfile.write(msg.encode())
                wfile.flush()
            except Exception:
                dead.append(wfile)
        for wfile in dead:
            _sse_clients.remove(wfile)


def check_for_new_files():
    """Check for new JSON files in history/ and import them."""
    with _import_lock:
        try:
            for filename in os.listdir(HISTORY_DIR):
                if not filename.endswith('.json'):
                    continue

                if filename in _known_files:
                    continue

                filepath = os.path.join(HISTORY_DIR, filename)
                try:
                    with open(filepath, 'r') as f:
                        game_data = json.load(f)

                    if import_game(DB_PATH, game_data, filename):
                        print(f"Imported new game: {filename}")
                        _notify_sse_clients({"type": "new_game", "filename": filename})

                    _known_files.add(filename)

                except (json.JSONDecodeError, IOError, KeyError) as e:
                    print(f"Error importing {filename}: {e}")

        except OSError:
            pass  # Directory doesn't exist or permission error


def _file_watcher():
    """Background thread that checks for new files every 2 seconds."""
    while True:
        check_for_new_files()
        time.sleep(2)


class PGCRHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=ROOT, **kwargs)

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path

        if path == "/":
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            with open(VIEWER_PATH, "rb") as f:
                self.wfile.write(f.read())
        elif path == "/api/events":
            self._serve_sse()
        elif path == "/overlay":
            self._serve_overlay()
        elif path == "/api/games":
            self._serve_game_list()
        elif path.startswith("/api/games/"):
            filename = path[11:]  # Remove "/api/games/"
            self._serve_game_detail(filename)
        elif path == "/api/players":
            query_params = parse_qs(parsed.query)
            player_name = query_params.get('name', [None])[0]
            if player_name:
                self._serve_player_stats(player_name)
            else:
                self._serve_all_players()
        elif path == "/api/pvp":
            query_params = parse_qs(parsed.query)
            player_name = query_params.get('player', [None])[0]
            if player_name:
                self._serve_pvp_stats(player_name)
            else:
                self.send_error(400, "Missing ?player= parameter")
        elif path.startswith("/api/leaderboard/"):
            stat = path[17:]  # Remove "/api/leaderboard/"
            query_params = parse_qs(parsed.query)
            limit = int(query_params.get('limit', [10])[0])
            self._serve_leaderboard(stat, limit)
        elif path.startswith("/history/"):
            # Serve from data/history/ directory
            filename = path[9:]  # Remove "/history/"
            filepath = os.path.join(HISTORY_DIR, filename)
            if os.path.isfile(filepath):
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self._add_cors_headers()
                self.end_headers()
                with open(filepath, "rb") as f:
                    self.wfile.write(f.read())
            else:
                self.send_error(404)
        elif path.startswith("/medals/"):
            super().do_GET()
        else:
            self.send_error(404)

    def _serve_sse(self):
        """Hold the connection open as a Server-Sent Events stream."""
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self._add_cors_headers()
        self.end_headers()

        with _sse_lock:
            _sse_clients.append(self.wfile)
        try:
            # Keep alive until client disconnects
            while True:
                time.sleep(30)
                self.wfile.write(b": keepalive\n\n")
                self.wfile.flush()
        except Exception:
            pass
        finally:
            with _sse_lock:
                if self.wfile in _sse_clients:
                    _sse_clients.remove(self.wfile)

    def _add_cors_headers(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def _serve_overlay(self):
        """Serve the streaming overlay page"""
        overlay_html = self._generate_overlay_html()
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self._add_cors_headers()
        self.end_headers()
        self.wfile.write(overlay_html.encode())

    def _generate_overlay_html(self):
        """Generate the overlay HTML page"""
        return '''<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>Halo 2 PGCR Overlay</title>
    <style>
        body {
            margin: 0;
            padding: 0;
            background: transparent;
            font-family: 'Courier New', monospace;
            color: #00ff00;
            width: 1920px;
            height: 1080px;
            overflow: hidden;
        }
        .overlay-container {
            position: absolute;
            bottom: 20px;
            right: 20px;
            background: rgba(0, 0, 0, 0.8);
            border: 2px solid #00ff00;
            border-radius: 10px;
            padding: 20px;
            max-width: 600px;
        }
        .game-title {
            font-size: 24px;
            font-weight: bold;
            margin-bottom: 15px;
            text-align: center;
        }
        .scoreboard {
            font-size: 16px;
        }
        .player-row {
            display: flex;
            justify-content: space-between;
            margin: 5px 0;
            padding: 3px 5px;
            background: rgba(0, 255, 0, 0.1);
        }
        .player-name {
            flex: 1;
            text-align: left;
        }
        .player-stats {
            display: flex;
            gap: 15px;
        }
    </style>
</head>
<body>
    <div class="overlay-container" id="overlayContent">
        <div class="game-title">Loading latest game...</div>
    </div>

    <script>
        async function updateOverlay() {
            try {
                const response = await fetch('/api/games');
                const games = await response.json();
                if (games.length > 0) {
                    const latestGame = games[0];
                    const gameResponse = await fetch(`/api/games/${latestGame.filename}`);
                    const gameData = await gameResponse.json();

                    let html = `<div class="game-title">${gameData.gametype} - ${new Date(gameData.timestamp).toLocaleTimeString()}</div>`;
                    html += '<div class="scoreboard">';

                    gameData.players.forEach(player => {
                        const kd = player.deaths > 0 ? (player.kills / player.deaths).toFixed(2) : player.kills;
                        html += `
                            <div class="player-row">
                                <div class="player-name">${player.name}</div>
                                <div class="player-stats">
                                    <span>K: ${player.kills}</span>
                                    <span>D: ${player.deaths}</span>
                                    <span>A: ${player.assists}</span>
                                    <span>K/D: ${kd}</span>
                                </div>
                            </div>
                        `;
                    });

                    html += '</div>';
                    document.getElementById('overlayContent').innerHTML = html;
                }
            } catch (e) {
                console.error('Failed to update overlay:', e);
            }
        }

        // Update every 5 seconds
        setInterval(updateOverlay, 5000);
        updateOverlay();
    </script>
</body>
</html>'''

    def _serve_game_list(self):
        """Serve list of all games from database."""
        try:
            games = get_all_games(DB_PATH)
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self._add_cors_headers()
            self.end_headers()
            self.wfile.write(json.dumps(games).encode())
        except Exception as e:
            print(f"Error serving game list: {e}")
            self.send_error(500)

    def _serve_game_detail(self, filename):
        """Serve individual game data from database."""
        try:
            game_data = get_game(DB_PATH, filename)
            if not game_data:
                self.send_error(404)
                return

            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self._add_cors_headers()
            self.end_headers()
            self.wfile.write(json.dumps(game_data).encode())
        except Exception as e:
            print(f"Error serving game detail for {filename}: {e}")
            self.send_error(500)

    def _serve_all_players(self):
        """Serve aggregate stats for all players from database."""
        try:
            players = get_all_players(DB_PATH)
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self._add_cors_headers()
            self.end_headers()
            self.wfile.write(json.dumps(players).encode())
        except Exception as e:
            print(f"Error serving all players: {e}")
            self.send_error(500)

    def _serve_player_stats(self, player_name):
        """Serve individual player career stats from database."""
        try:
            player_data = get_player(DB_PATH, player_name)
            if not player_data:
                self.send_error(404)
                return

            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self._add_cors_headers()
            self.end_headers()
            self.wfile.write(json.dumps(player_data).encode())
        except Exception as e:
            print(f"Error serving player stats for {player_name}: {e}")
            self.send_error(500)

    def _serve_pvp_stats(self, player_name):
        """Serve head-to-head PvP stats for a player."""
        try:
            pvp_data = get_pvp_stats(DB_PATH, player_name)
            if not pvp_data:
                self.send_error(404)
                return

            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self._add_cors_headers()
            self.end_headers()
            self.wfile.write(json.dumps(pvp_data).encode())
        except Exception as e:
            print(f"Error serving PvP stats for {player_name}: {e}")
            self.send_error(500)

    def _serve_leaderboard(self, stat, limit):
        """Serve leaderboard for a specific stat."""
        try:
            leaderboard = get_leaderboard(DB_PATH, stat, limit)
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self._add_cors_headers()
            self.end_headers()
            self.wfile.write(json.dumps(leaderboard).encode())
        except ValueError as e:
            # Invalid stat name
            self.send_error(400, str(e))
        except Exception as e:
            print(f"Error serving leaderboard for {stat}: {e}")
            self.send_error(500)

    def log_message(self, fmt, *args):
        pass  # quiet


def initialize_database():
    """Initialize database and import existing history if needed."""
    global _known_files
    print(f"Initializing database: {DB_PATH}")
    init_db(DB_PATH)

    # Check if we need to import existing history
    if os.path.exists(HISTORY_DIR):
        print(f"Importing existing history from: {HISTORY_DIR}")
        stats = import_history_dir(DB_PATH, HISTORY_DIR)

        if stats['imported'] > 0:
            print(f"Imported {stats['imported']} existing games")
        if stats['skipped'] > 0:
            print(f"Skipped {stats['skipped']} games (already in DB)")
        if stats['errors'] > 0:
            print(f"Failed to import {stats['errors']} files")

        # Seed known files set so check_for_new_files only processes truly new files
        _known_files = {f for f in os.listdir(HISTORY_DIR) if f.endswith('.json')}

    print("Database ready!")


def start_tunnel(port):
    """Try to start a Cloudflare quick tunnel. Returns the process or None."""
    cloudflared = shutil.which("cloudflared")
    if not cloudflared:
        # Check common user-local install path
        local_bin = os.path.expanduser("~/.local/bin/cloudflared")
        if os.path.isfile(local_bin) and os.access(local_bin, os.X_OK):
            cloudflared = local_bin
        else:
            print("cloudflared not found — skipping tunnel (install it for public URL)")
            return None

    try:
        proc = subprocess.Popen(
            [cloudflared, "tunnel", "--url", f"http://localhost:{port}"],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
    except OSError as e:
        print(f"Failed to start cloudflared: {e}")
        return None

    def _watch():
        for line in proc.stdout:
            line = line.strip()
            # Look for the actual tunnel URL (has a subdomain before trycloudflare.com)
            if ".trycloudflare.com" in line:
                for part in line.split():
                    if ".trycloudflare.com" in part:
                        url = part if part.startswith("http") else f"https://{part}"
                        print(f"Public URL: {url}")
                        break
            elif "ERR" in line or "error" in line.lower():
                print(f"cloudflared: {line}")

    thread = threading.Thread(target=_watch, daemon=True)
    thread.start()
    return proc


def main():
    signal.signal(signal.SIGTERM, lambda s, f: sys.exit(0))

    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8080

    # Initialize database on startup
    initialize_database()

    # Start background file watcher
    watcher = threading.Thread(target=_file_watcher, daemon=True)
    watcher.start()

    # Start Cloudflare tunnel (best-effort)
    tunnel_proc = start_tunnel(port)

    server = ThreadingHTTPServer(("0.0.0.0", port), PGCRHandler)
    server.daemon_threads = True
    print(f"PGCR Viewer running at http://localhost:{port}")
    print("Press Ctrl+C to stop")
    try:
        server.serve_forever()
    except (KeyboardInterrupt, SystemExit):
        if tunnel_proc:
            tunnel_proc.terminate()
        server.shutdown()
        print("\nStopped.")


if __name__ == "__main__":
    main()
