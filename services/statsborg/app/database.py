"""SQLite database backend for StatsBorg.

Provides persistent storage for game statistics with thread-safe operations.
Uses Python stdlib sqlite3 only - no external dependencies.
"""
import sqlite3
import json
import os
import threading
from contextlib import contextmanager
from collections import defaultdict
from typing import Dict, List, Optional, Any


# Thread-local storage for database connections
_local = threading.local()


@contextmanager
def get_db_connection(db_path: str):
    """Get a thread-safe database connection."""
    if not hasattr(_local, 'connections'):
        _local.connections = {}
    
    if db_path not in _local.connections:
        conn = sqlite3.connect(db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row  # Enable dict-like access
        _local.connections[db_path] = conn
    
    yield _local.connections[db_path]


def init_db(db_path: str) -> None:
    """Initialize database with required tables and indexes."""
    with get_db_connection(db_path) as conn:
        # Create tables
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS games (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            filename TEXT UNIQUE NOT NULL,
            fingerprint TEXT,
            timestamp TEXT,
            gametype TEXT,
            gametype_id INTEGER,
            player_count INTEGER,
            source TEXT,
            schema_version INTEGER,
            raw_json TEXT
        );

        CREATE TABLE IF NOT EXISTS players (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            game_id INTEGER REFERENCES games(id),
            name TEXT NOT NULL,
            display_name TEXT,
            kills INTEGER DEFAULT 0,
            deaths INTEGER DEFAULT 0,
            assists INTEGER DEFAULT 0,
            suicides INTEGER DEFAULT 0,
            place INTEGER,
            place_string TEXT,
            team_index INTEGER,
            score_string TEXT,
            rank INTEGER DEFAULT 0,
            observer BOOLEAN DEFAULT 0,
            medals_earned INTEGER DEFAULT 0,
            medals_bitmask INTEGER DEFAULT 0,
            total_shots INTEGER DEFAULT 0,
            shots_hit INTEGER DEFAULT 0,
            headshots INTEGER DEFAULT 0,
            gametype_value_0 INTEGER DEFAULT 0,
            gametype_value_1 INTEGER DEFAULT 0,
            killed_json TEXT
        );

        CREATE TABLE IF NOT EXISTS teams (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            game_id INTEGER REFERENCES games(id),
            team_id INTEGER,
            name TEXT,
            score INTEGER DEFAULT 0,
            score_string TEXT,
            place INTEGER,
            round_score INTEGER DEFAULT 0
        );

        -- Create indexes if they don't exist
        CREATE INDEX IF NOT EXISTS idx_players_name ON players(name);
        CREATE INDEX IF NOT EXISTS idx_players_game ON players(game_id);
        CREATE INDEX IF NOT EXISTS idx_games_timestamp ON games(timestamp);
        CREATE INDEX IF NOT EXISTS idx_games_gametype ON games(gametype);
        CREATE INDEX IF NOT EXISTS idx_teams_game ON teams(game_id);
        CREATE INDEX IF NOT EXISTS idx_games_fingerprint ON games(fingerprint);
        """)
        conn.commit()


def import_game(db_path: str, game_dict: Dict[str, Any], filename: str) -> bool:
    """Import a single game JSON dict into the database.
    
    Returns True if imported, False if skipped (duplicate fingerprint).
    """
    with get_db_connection(db_path) as conn:
        # Check if we already have this game (by fingerprint or filename)
        fingerprint = game_dict.get('fingerprint')
        cursor = conn.cursor()
        
        if fingerprint:
            cursor.execute("SELECT id FROM games WHERE fingerprint = ?", (fingerprint,))
        else:
            cursor.execute("SELECT id FROM games WHERE filename = ?", (filename,))
        
        if cursor.fetchone():
            return False  # Already exists, skip
        
        # Insert game record
        cursor.execute("""
            INSERT INTO games (filename, fingerprint, timestamp, gametype, gametype_id, 
                             player_count, source, schema_version, raw_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            filename,
            game_dict.get('fingerprint'),
            game_dict.get('timestamp'),
            game_dict.get('gametype'),
            game_dict.get('gametype_id'),
            game_dict.get('player_count'),
            game_dict.get('source'),
            game_dict.get('schema_version'),
            json.dumps(game_dict)
        ))
        
        game_id = cursor.lastrowid
        
        # Insert players
        for player in (game_dict.get('players') or []):
            killed_json = json.dumps(player.get('killed', []))
            cursor.execute("""
                INSERT INTO players (game_id, name, display_name, kills, deaths, assists, 
                                   suicides, place, place_string, team_index, score_string,
                                   rank, observer, medals_earned, medals_bitmask, 
                                   total_shots, shots_hit, headshots, gametype_value_0,
                                   gametype_value_1, killed_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                game_id, player.get('name'), player.get('display_name'),
                player.get('kills', 0), player.get('deaths', 0), player.get('assists', 0),
                player.get('suicides', 0), player.get('place'), player.get('place_string'),
                player.get('team_index'), player.get('score_string'), player.get('rank', 0),
                player.get('observer', False), player.get('medals_earned', 0),
                player.get('medals_bitmask', 0), player.get('total_shots', 0),
                player.get('shots_hit', 0), player.get('headshots', 0),
                player.get('gametype_value_0', 0), player.get('gametype_value_1', 0),
                killed_json
            ))
        
        # Insert teams
        for team in (game_dict.get('teams') or []):
            cursor.execute("""
                INSERT INTO teams (game_id, team_id, name, score, score_string, place, round_score)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                game_id, team.get('team_id'), team.get('name'),
                team.get('score', 0), team.get('score_string'),
                team.get('place'), team.get('round_score', 0)
            ))
        
        conn.commit()
        return True


def import_history_dir(db_path: str, history_dir: str) -> Dict[str, int]:
    """Bulk import all JSON files from history directory.
    
    Returns dict with import stats: {'imported': count, 'skipped': count, 'errors': count}.
    """
    stats = {'imported': 0, 'skipped': 0, 'errors': 0}
    
    if not os.path.exists(history_dir):
        return stats
    
    for filename in os.listdir(history_dir):
        if not filename.endswith('.json'):
            continue
        
        filepath = os.path.join(history_dir, filename)
        try:
            with open(filepath, 'r') as f:
                game_data = json.load(f)
            
            if import_game(db_path, game_data, filename):
                stats['imported'] += 1
            else:
                stats['skipped'] += 1
                
        except (json.JSONDecodeError, IOError, KeyError) as e:
            print(f"Error importing {filename}: {e}")
            stats['errors'] += 1
    
    return stats


def get_all_games(db_path: str) -> List[Dict[str, Any]]:
    """Return list of all games for API (sorted by timestamp descending)."""
    with get_db_connection(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT g.filename, g.timestamp, g.gametype, g.player_count, g.raw_json,
                   GROUP_CONCAT(t.name) as team_names,
                   GROUP_CONCAT(t.score_string) as team_scores,
                   GROUP_CONCAT(t.team_id) as team_ids,
                   GROUP_CONCAT(t.place) as team_places
            FROM games g
            LEFT JOIN teams t ON g.id = t.game_id
            GROUP BY g.id
            ORDER BY g.timestamp DESC
        """)

        games = []
        for row in cursor.fetchall():
            # Extract map/variant from raw_json if available
            map_name = ""
            variant = ""
            if row['raw_json']:
                try:
                    rj = json.loads(row['raw_json'])
                    map_name = rj.get('map', '')
                    variant = rj.get('variant', '')
                except (json.JSONDecodeError, TypeError):
                    pass

            game_entry = {
                "filename": row['filename'],
                "timestamp": row['timestamp'] or "",
                "gametype": row['gametype'] or "unknown",
                "player_count": row['player_count'] or 0,
                "map": map_name,
                "variant": variant,
                "winner": "",
                "teams": []
            }
            
            # Parse team data if available
            if row['team_names']:
                team_names = row['team_names'].split(',')
                team_scores = row['team_scores'].split(',')
                team_ids = row['team_ids'].split(',')
                team_places = row['team_places'].split(',')
                
                teams_data = []
                for i in range(len(team_names)):
                    teams_data.append({
                        'name': team_names[i],
                        'score_string': team_scores[i] if i < len(team_scores) else '0',
                        'team_id': int(team_ids[i]) if i < len(team_ids) else 0,
                        'place': int(team_places[i]) if i < len(team_places) and team_places[i] else 99
                    })
                
                # Sort teams by place
                teams_data.sort(key=lambda t: t['place'])
                game_entry['teams'] = teams_data
            else:
                # No teams, get winner from players
                cursor.execute("""
                    SELECT name, score_string FROM players 
                    WHERE game_id = (SELECT id FROM games WHERE filename = ?)
                    ORDER BY place LIMIT 1
                """, (row['filename'],))
                winner_row = cursor.fetchone()
                if winner_row:
                    game_entry['winner'] = f"{winner_row['name']} ({winner_row['score_string'] or '?'})"
            
            games.append(game_entry)
        
        return games


def get_game(db_path: str, filename: str) -> Optional[Dict[str, Any]]:
    """Return full game data reconstructed from database."""
    with get_db_connection(db_path) as conn:
        cursor = conn.cursor()
        
        # Get game record
        cursor.execute("SELECT * FROM games WHERE filename = ?", (filename,))
        game_row = cursor.fetchone()
        if not game_row:
            return None
        
        # Start with raw JSON if available for compatibility
        if game_row['raw_json']:
            try:
                game_data = json.loads(game_row['raw_json'])
            except json.JSONDecodeError:
                game_data = {}
        else:
            game_data = {}
        
        # Overlay with database fields (in case JSON is partial/missing)
        game_data.update({
            'schema_version': game_row['schema_version'],
            'timestamp': game_row['timestamp'],
            'fingerprint': game_row['fingerprint'],
            'source': game_row['source'],
            'gametype': game_row['gametype'],
            'gametype_id': game_row['gametype_id'],
            'player_count': game_row['player_count']
        })
        
        # Prefer raw_json players/teams (preserves nested medals, accuracy, gametype_stats)
        if 'players' in game_data and game_data['players']:
            # raw_json already has the correct nested format — use it directly
            pass
        else:
            # Fallback: reconstruct from flattened DB columns
            cursor.execute("""
                SELECT * FROM players WHERE game_id = ? ORDER BY place
            """, (game_row['id'],))

            players = []
            for player_row in cursor.fetchall():
                player_data = {
                    'name': player_row['name'],
                    'display_name': player_row['display_name'],
                    'kills': player_row['kills'],
                    'deaths': player_row['deaths'],
                    'assists': player_row['assists'],
                    'suicides': player_row['suicides'],
                    'place': player_row['place'],
                    'place_string': player_row['place_string'],
                    'team': player_row['team_index'],
                    'score_string': player_row['score_string'],
                    'rank': player_row['rank'],
                    'observer': bool(player_row['observer']),
                    'medals': {
                        'total': player_row['medals_earned'],
                        'by_type': player_row['medals_bitmask']
                    },
                    'accuracy': {
                        'total_shots': player_row['total_shots'],
                        'shots_hit': player_row['shots_hit'],
                        'headshots': player_row['headshots'],
                        'percentage': round((player_row['shots_hit'] / max(player_row['total_shots'], 1)) * 100, 1) if player_row['total_shots'] else 0
                    },
                    'gametype_values': [player_row['gametype_value_0'], player_row['gametype_value_1']]
                }

                if player_row['killed_json']:
                    try:
                        player_data['killed'] = json.loads(player_row['killed_json'])
                    except json.JSONDecodeError:
                        player_data['killed'] = []

                players.append(player_data)

            game_data['players'] = players

        if 'teams' not in game_data or not game_data['teams']:
            cursor.execute("""
                SELECT * FROM teams WHERE game_id = ? ORDER BY place
            """, (game_row['id'],))

            teams = []
            for team_row in cursor.fetchall():
                teams.append({
                    'team_id': team_row['team_id'],
                    'name': team_row['name'],
                    'score': team_row['score'],
                    'score_string': team_row['score_string'],
                    'place': team_row['place'],
                    'round_score': team_row['round_score']
                })

            game_data['teams'] = teams

        return game_data


def get_all_players(db_path: str) -> List[Dict[str, Any]]:
    """Get aggregate career stats for all players."""
    with get_db_connection(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT 
                p.name,
                COUNT(*) as games_played,
                SUM(p.kills) as total_kills,
                SUM(p.deaths) as total_deaths,
                SUM(p.assists) as total_assists,
                SUM(p.suicides) as total_suicides,
                SUM(p.total_shots) as total_shots,
                SUM(p.shots_hit) as total_hits,
                SUM(p.headshots) as total_headshots,
                SUM(p.medals_earned) as total_medals,
                SUM(CASE WHEN p.place = 0 THEN 1 ELSE 0 END) as wins,
                GROUP_CONCAT(DISTINCT g.gametype) as gametypes
            FROM players p
            JOIN games g ON p.game_id = g.id
            WHERE p.observer = 0
            GROUP BY p.name
            ORDER BY total_kills DESC
        """)
        
        result = []
        for row in cursor.fetchall():
            stats = {
                'name': row['name'],
                'games_played': row['games_played'],
                'total_kills': row['total_kills'] or 0,
                'total_deaths': row['total_deaths'] or 0,
                'total_assists': row['total_assists'] or 0,
                'total_suicides': row['total_suicides'] or 0,
                'total_shots': row['total_shots'] or 0,
                'total_hits': row['total_hits'] or 0,
                'total_headshots': row['total_headshots'] or 0,
                'total_medals': row['total_medals'] or 0,
                'wins': row['wins'] or 0,
                'gametypes': row['gametypes'].split(',') if row['gametypes'] else []
            }
            
            # Calculate derived stats
            stats['kd_ratio'] = stats['total_kills'] / max(stats['total_deaths'], 1)
            stats['accuracy'] = (stats['total_hits'] / max(stats['total_shots'], 1)) * 100 if stats['total_shots'] > 0 else 0
            stats['win_rate'] = (stats['wins'] / max(stats['games_played'], 1)) * 100
            
            result.append(stats)
        
        return result


def get_player(db_path: str, name: str) -> Optional[Dict[str, Any]]:
    """Get individual player career stats and recent games."""
    with get_db_connection(db_path) as conn:
        cursor = conn.cursor()
        
        # Get aggregate stats
        cursor.execute("""
            SELECT 
                COUNT(*) as games_played,
                SUM(p.kills) as total_kills,
                SUM(p.deaths) as total_deaths,
                SUM(p.assists) as total_assists,
                SUM(p.suicides) as total_suicides,
                SUM(p.total_shots) as total_shots,
                SUM(p.shots_hit) as total_hits,
                SUM(p.headshots) as total_headshots,
                SUM(p.medals_earned) as total_medals,
                SUM(CASE WHEN p.place = 0 THEN 1 ELSE 0 END) as wins
            FROM players p
            WHERE LOWER(p.name) = LOWER(?) AND p.observer = 0
        """, (name,))
        
        stats_row = cursor.fetchone()
        if not stats_row or stats_row['games_played'] == 0:
            return None
        
        # Get gametype breakdown
        cursor.execute("""
            SELECT g.gametype, COUNT(*) as count
            FROM players p
            JOIN games g ON p.game_id = g.id
            WHERE LOWER(p.name) = LOWER(?) AND p.observer = 0
            GROUP BY g.gametype
        """, (name,))
        
        gametypes = {}
        for row in cursor.fetchall():
            gametypes[row['gametype']] = row['count']
        
        # Get recent games (last 10)
        cursor.execute("""
            SELECT g.timestamp, g.gametype, g.filename,
                   p.kills, p.deaths, p.assists, p.place, p.place_string
            FROM players p
            JOIN games g ON p.game_id = g.id
            WHERE LOWER(p.name) = LOWER(?) AND p.observer = 0
            ORDER BY g.timestamp DESC
            LIMIT 10
        """, (name,))
        
        recent_games = []
        for row in cursor.fetchall():
            recent_games.append({
                'timestamp': row['timestamp'],
                'gametype': row['gametype'],
                'filename': row['filename'],
                'kills': row['kills'],
                'deaths': row['deaths'],
                'assists': row['assists'],
                'place': row['place'],
                'place_string': row['place_string']
            })
        
        # Best and worst game by K/D
        cursor.execute("""
            SELECT g.filename, g.gametype, p.kills, p.deaths,
                   CAST(p.kills AS REAL) / MAX(p.deaths, 1) as kd
            FROM players p
            JOIN games g ON p.game_id = g.id
            WHERE LOWER(p.name) = LOWER(?) AND p.observer = 0
            ORDER BY kd DESC LIMIT 1
        """, (name,))
        best_row = cursor.fetchone()

        cursor.execute("""
            SELECT g.filename, g.gametype, p.kills, p.deaths,
                   CAST(p.kills AS REAL) / MAX(p.deaths, 1) as kd
            FROM players p
            JOIN games g ON p.game_id = g.id
            WHERE LOWER(p.name) = LOWER(?) AND p.observer = 0
            ORDER BY kd ASC LIMIT 1
        """, (name,))
        worst_row = cursor.fetchone()

        # Nemesis: opponent who killed this player the most
        nemesis = None
        cursor.execute("""
            SELECT g.raw_json, g.id FROM games g
            JOIN players p ON p.game_id = g.id
            WHERE LOWER(p.name) = LOWER(?) AND p.observer = 0 AND g.raw_json IS NOT NULL
        """, (name,))

        death_counts = defaultdict(int)
        for grow in cursor.fetchall():
            try:
                gdata = json.loads(grow['raw_json'])
                players_list = gdata.get('players', [])
                # Find this player's index
                target_idx = None
                for i, p in enumerate(players_list):
                    if p.get('name', '').lower() == name.lower():
                        target_idx = i
                        break
                if target_idx is None:
                    continue
                # Count how many times each opponent killed this player
                for i, p in enumerate(players_list):
                    if i == target_idx:
                        continue
                    killed_arr = p.get('killed', [])
                    if target_idx < len(killed_arr):
                        death_counts[p['name']] += killed_arr[target_idx]
            except (json.JSONDecodeError, KeyError):
                continue

        if death_counts:
            nemesis_name = max(death_counts, key=death_counts.get)
            nemesis = {'name': nemesis_name, 'times_beaten': death_counts[nemesis_name]}

        # Favorite gametype
        favorite_gametype = None
        if gametypes:
            fav_gt = max(gametypes, key=gametypes.get)
            favorite_gametype = {'gametype': fav_gt, 'count': gametypes[fav_gt]}

        # Build result
        result = {
            'name': name,
            'games_played': stats_row['games_played'],
            'total_kills': stats_row['total_kills'] or 0,
            'total_deaths': stats_row['total_deaths'] or 0,
            'total_assists': stats_row['total_assists'] or 0,
            'total_suicides': stats_row['total_suicides'] or 0,
            'total_shots': stats_row['total_shots'] or 0,
            'total_hits': stats_row['total_hits'] or 0,
            'total_headshots': stats_row['total_headshots'] or 0,
            'total_medals': stats_row['total_medals'] or 0,
            'wins': stats_row['wins'] or 0,
            'gametypes': gametypes,
            'recent_games': recent_games,
            'favorite_gametype': favorite_gametype,
            'nemesis': nemesis
        }

        if best_row:
            result['best_game'] = {
                'filename': best_row['filename'],
                'gametype': best_row['gametype'],
                'kd_ratio': round(best_row['kd'], 2)
            }
        if worst_row:
            result['worst_game'] = {
                'filename': worst_row['filename'],
                'gametype': worst_row['gametype'],
                'kd_ratio': round(worst_row['kd'], 2)
            }

        # Calculate derived stats
        result['kd_ratio'] = result['total_kills'] / max(result['total_deaths'], 1)
        result['accuracy'] = (result['total_hits'] / max(result['total_shots'], 1)) * 100 if result['total_shots'] > 0 else 0
        result['win_rate'] = (result['wins'] / max(result['games_played'], 1)) * 100

        return result


def get_leaderboard(db_path: str, stat: str, limit: int = 10) -> List[Dict[str, Any]]:
    """Get top N players by any stat.
    
    Valid stats: kills, deaths, assists, kd_ratio, accuracy, wins, games_played, etc.
    """
    with get_db_connection(db_path) as conn:
        cursor = conn.cursor()
        
        # Map stat names to SQL expressions
        stat_mapping = {
            'kills': 'SUM(p.kills)',
            'deaths': 'SUM(p.deaths)',
            'assists': 'SUM(p.assists)',
            'suicides': 'SUM(p.suicides)',
            'shots': 'SUM(p.total_shots)',
            'hits': 'SUM(p.shots_hit)',
            'headshots': 'SUM(p.headshots)',
            'medals': 'SUM(p.medals_earned)',
            'games': 'COUNT(*)',
            'wins': 'SUM(CASE WHEN p.place = 0 THEN 1 ELSE 0 END)',
            'kd_ratio': 'CAST(SUM(p.kills) AS REAL) / MAX(SUM(p.deaths), 1)',
            'accuracy': 'CAST(SUM(p.shots_hit) AS REAL) / MAX(SUM(p.total_shots), 1) * 100'
        }
        
        if stat not in stat_mapping:
            raise ValueError(f"Invalid stat: {stat}. Valid options: {list(stat_mapping.keys())}")
        
        query = f"""
            SELECT 
                p.name,
                COUNT(*) as games_played,
                SUM(p.kills) as total_kills,
                SUM(p.deaths) as total_deaths,
                SUM(p.assists) as total_assists,
                SUM(p.total_shots) as total_shots,
                SUM(p.shots_hit) as total_hits,
                SUM(p.headshots) as total_headshots,
                SUM(p.medals_earned) as total_medals,
                SUM(CASE WHEN p.place = 0 THEN 1 ELSE 0 END) as wins,
                {stat_mapping[stat]} as stat_value
            FROM players p
            WHERE p.observer = 0
            GROUP BY p.name
            ORDER BY stat_value DESC
            LIMIT ?
        """
        
        cursor.execute(query, (limit,))
        
        result = []
        for row in cursor.fetchall():
            player_stats = {
                'name': row['name'],
                'games_played': row['games_played'],
                'total_kills': row['total_kills'] or 0,
                'total_deaths': row['total_deaths'] or 0,
                'total_assists': row['total_assists'] or 0,
                'total_shots': row['total_shots'] or 0,
                'total_hits': row['total_hits'] or 0,
                'total_headshots': row['total_headshots'] or 0,
                'total_medals': row['total_medals'] or 0,
                'wins': row['wins'] or 0,
                'stat_value': row['stat_value'],
                'stat_name': stat
            }
            
            # Add derived stats
            player_stats['kd_ratio'] = player_stats['total_kills'] / max(player_stats['total_deaths'], 1)
            player_stats['accuracy'] = (player_stats['total_hits'] / max(player_stats['total_shots'], 1)) * 100 if player_stats['total_shots'] > 0 else 0
            player_stats['win_rate'] = (player_stats['wins'] / max(player_stats['games_played'], 1)) * 100
            
            result.append(player_stats)

        return result


def get_pvp_stats(db_path: str, player_name: str) -> Optional[Dict[str, Any]]:
    """Get head-to-head kill stats for a player vs all opponents."""
    with get_db_connection(db_path) as conn:
        cursor = conn.cursor()

        cursor.execute("""
            SELECT g.raw_json FROM games g
            JOIN players p ON p.game_id = g.id
            WHERE LOWER(p.name) = LOWER(?) AND p.observer = 0 AND g.raw_json IS NOT NULL
        """, (player_name,))

        kills_given = defaultdict(int)  # how many times we killed them
        kills_received = defaultdict(int)  # how many times they killed us

        for row in cursor.fetchall():
            try:
                gdata = json.loads(row['raw_json'])
                players_list = gdata.get('players', [])

                target_idx = None
                for i, p in enumerate(players_list):
                    if p.get('name', '').lower() == player_name.lower():
                        target_idx = i
                        break
                if target_idx is None:
                    continue

                target = players_list[target_idx]
                target_killed = target.get('killed', [])

                for i, p in enumerate(players_list):
                    if i == target_idx:
                        continue
                    opp_name = p.get('name', '')
                    # Kills we got on them
                    if i < len(target_killed):
                        kills_given[opp_name] += target_killed[i]
                    # Kills they got on us
                    opp_killed = p.get('killed', [])
                    if target_idx < len(opp_killed):
                        kills_received[opp_name] += opp_killed[target_idx]

            except (json.JSONDecodeError, KeyError):
                continue

        all_opponents = set(kills_given.keys()) | set(kills_received.keys())
        opponents = []
        for opp in all_opponents:
            k = kills_given.get(opp, 0)
            d = kills_received.get(opp, 0)
            opponents.append({
                'name': opp,
                'kills': k,
                'deaths': d,
                'net': k - d
            })

        opponents.sort(key=lambda x: x['kills'] + x['deaths'], reverse=True)

        return {'opponents': opponents}