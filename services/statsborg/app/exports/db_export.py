#!/usr/bin/env python3
"""
Halo 2 Game History -> PostgreSQL Export

Imports game history JSON files into a PostgreSQL database for analysis.

Requirements:
    pip install psycopg2-binary

Usage:
    # Create database tables
    python db_export.py --init-schema

    # Import all history files
    python db_export.py --import-history

    # Import a single file
    python db_export.py --import-file history/2026-02-05_20-37-19_3f33d2f6.json

    # Print aggregate stats
    python db_export.py --summary

Connection:
    Set DATABASE_URL env var or use --db-url flag.
    Example: DATABASE_URL=postgresql://user:pass@localhost:5432/halo2
"""

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path

try:
    import psycopg2
    import psycopg2.extras
except ImportError:
    psycopg2 = None


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS games (
    id             SERIAL PRIMARY KEY,
    timestamp      TIMESTAMPTZ NOT NULL,
    fingerprint    VARCHAR(32) UNIQUE NOT NULL,
    source         VARCHAR(20),
    gametype_id    SMALLINT,
    gametype       VARCHAR(20),
    player_count   SMALLINT,
    schema_version SMALLINT DEFAULT 1,
    raw_json       JSONB,
    created_at     TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS teams (
    id          SERIAL PRIMARY KEY,
    game_id     INTEGER REFERENCES games(id) ON DELETE CASCADE,
    team_index  SMALLINT NOT NULL,
    name        VARCHAR(64),
    score       INTEGER,
    place       SMALLINT,
    UNIQUE(game_id, team_index)
);

CREATE TABLE IF NOT EXISTS players (
    id               SERIAL PRIMARY KEY,
    game_id          INTEGER REFERENCES games(id) ON DELETE CASCADE,
    player_name      VARCHAR(32) NOT NULL,
    display_name     VARCHAR(32),
    score_string     VARCHAR(32),
    place            SMALLINT,
    place_string     VARCHAR(8),
    kills            INTEGER,
    deaths           INTEGER,
    assists          INTEGER,
    suicides         INTEGER,
    kd_ratio         REAL,
    medals_total     INTEGER,
    medals_bitmask   INTEGER,
    total_shots      INTEGER,
    shots_hit        INTEGER,
    headshots        INTEGER,
    accuracy_pct     REAL,
    gametype_value0  INTEGER,
    gametype_value1  INTEGER,
    killed_array     INTEGER[],
    UNIQUE(game_id, player_name)
);
"""


class Halo2Database:
    """PostgreSQL interface for Halo 2 game history."""

    def __init__(self, db_url=None):
        """
        Connect using db_url or DATABASE_URL env var.

        Args:
            db_url: PostgreSQL connection string. Falls back to DATABASE_URL env var.

        Raises:
            ImportError: If psycopg2 is not installed.
            Exception: If connection fails.
        """
        if psycopg2 is None:
            raise ImportError(
                "psycopg2 is required for database export.\n"
                "Install it with: pip install psycopg2-binary"
            )

        url = db_url or os.environ.get("DATABASE_URL")
        if not url:
            raise ValueError("No database URL provided. Set DATABASE_URL or pass db_url.")

        self.conn = psycopg2.connect(url)
        self.conn.autocommit = False

    def init_schema(self):
        """Create tables if they do not exist."""
        with self.conn.cursor() as cur:
            cur.execute(SCHEMA_SQL)
        self.conn.commit()
        print("Schema initialized (3 tables: games, teams, players).")

    def import_snapshot(self, snapshot: dict) -> bool:
        """
        Import one game snapshot. Skip if fingerprint already exists.

        Args:
            snapshot: Parsed JSON dict from a history file.

        Returns:
            True if inserted, False if skipped (duplicate fingerprint).
        """
        fingerprint = snapshot.get("fingerprint")
        if not fingerprint:
            print("  WARNING: Snapshot missing fingerprint, skipping.", file=sys.stderr)
            return False

        # Check for duplicate
        with self.conn.cursor() as cur:
            cur.execute("SELECT id FROM games WHERE fingerprint = %s", (fingerprint,))
            if cur.fetchone():
                return False

        try:
            game_id = self._insert_game(snapshot)
            self._insert_teams(game_id, snapshot)
            self._insert_players(game_id, snapshot)
            self.conn.commit()
            return True
        except Exception:
            self.conn.rollback()
            raise

    def _insert_game(self, snapshot: dict) -> int:
        """Insert a row into the games table and return its id."""
        timestamp_str = snapshot.get("timestamp", "")
        try:
            ts = datetime.fromisoformat(timestamp_str)
        except (ValueError, TypeError):
            ts = datetime.now()

        with self.conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO games (timestamp, fingerprint, source, gametype_id,
                                   gametype, player_count, schema_version, raw_json)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id
                """,
                (
                    ts,
                    snapshot.get("fingerprint"),
                    snapshot.get("source"),
                    snapshot.get("gametype_id"),       # None for v1 files
                    snapshot.get("gametype"),
                    snapshot.get("player_count", 0),
                    snapshot.get("schema_version", 1),
                    json.dumps(snapshot),
                ),
            )
            return cur.fetchone()[0]

    def _insert_teams(self, game_id: int, snapshot: dict):
        """Insert team rows if the snapshot contains team data."""
        teams = snapshot.get("teams")
        if not teams:
            return

        with self.conn.cursor() as cur:
            for team in teams:
                cur.execute(
                    """
                    INSERT INTO teams (game_id, team_index, name, score, place)
                    VALUES (%s, %s, %s, %s, %s)
                    ON CONFLICT (game_id, team_index) DO NOTHING
                    """,
                    (
                        game_id,
                        team.get("index", 0),
                        team.get("name"),
                        team.get("score"),
                        team.get("place"),
                    ),
                )

    def _insert_players(self, game_id: int, snapshot: dict):
        """Insert player rows for the game."""
        players_data = snapshot.get("players", [])

        with self.conn.cursor() as cur:
            for p in players_data:
                player_name = p.get("name", "")
                if not player_name:
                    continue

                # Extract medals (handle both nested and flat formats)
                medals = p.get("medals", {})
                if isinstance(medals, dict):
                    medals_total = medals.get("total")
                    medals_bitmask = medals.get("by_type")
                else:
                    medals_total = None
                    medals_bitmask = None

                # Extract accuracy (handle both nested and flat formats)
                accuracy = p.get("accuracy", {})
                if isinstance(accuracy, dict):
                    total_shots = accuracy.get("total_shots")
                    shots_hit = accuracy.get("shots_hit")
                    headshots = accuracy.get("headshots")
                    accuracy_pct = accuracy.get("percentage")
                else:
                    total_shots = None
                    shots_hit = None
                    headshots = None
                    accuracy_pct = None

                # Extract gametype values
                gt_values = p.get("gametype_values", [])
                gametype_value0 = gt_values[0] if len(gt_values) > 0 else None
                gametype_value1 = gt_values[1] if len(gt_values) > 1 else None

                # Extract killed array -- field is "killed" in newer files,
                # "killed_by" in older (v1) PGCRDisplayStats-based files
                killed_array = p.get("killed") or p.get("killed_by")

                # K/D ratio: use stored value or compute
                kd_ratio = p.get("kd_ratio")
                if kd_ratio is None:
                    kills = p.get("kills", 0) or 0
                    deaths = p.get("deaths", 0) or 0
                    kd_ratio = round(kills / max(deaths, 1), 2)

                cur.execute(
                    """
                    INSERT INTO players (
                        game_id, player_name, display_name, score_string,
                        place, place_string, kills, deaths, assists, suicides,
                        kd_ratio, medals_total, medals_bitmask,
                        total_shots, shots_hit, headshots, accuracy_pct,
                        gametype_value0, gametype_value1, killed_array
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                            %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (game_id, player_name) DO NOTHING
                    """,
                    (
                        game_id,
                        player_name[:32],
                        (p.get("display_name") or "")[:32],
                        (p.get("score_string") or "")[:32],
                        p.get("place"),
                        (p.get("place_string") or "")[:8],
                        p.get("kills"),
                        p.get("deaths"),
                        p.get("assists"),
                        p.get("suicides"),
                        kd_ratio,
                        medals_total,
                        medals_bitmask,
                        total_shots,
                        shots_hit,
                        headshots,
                        accuracy_pct,
                        gametype_value0,
                        gametype_value1,
                        killed_array,
                    ),
                )

    def import_history_dir(self, history_dir: str) -> tuple:
        """
        Import all JSON files from a history directory.

        Args:
            history_dir: Path to directory containing JSON history files.

        Returns:
            Tuple of (imported_count, skipped_count).
        """
        history_path = Path(history_dir)
        if not history_path.is_dir():
            print(f"ERROR: Directory not found: {history_dir}", file=sys.stderr)
            return (0, 0)

        json_files = sorted(history_path.glob("*.json"))
        if not json_files:
            print(f"No JSON files found in {history_dir}")
            return (0, 0)

        imported = 0
        skipped = 0

        for filepath in json_files:
            try:
                with open(filepath, "r", encoding="utf-8") as f:
                    snapshot = json.load(f)

                if self.import_snapshot(snapshot):
                    imported += 1
                    print(f"  Imported: {filepath.name}")
                else:
                    skipped += 1
            except json.JSONDecodeError as e:
                print(f"  ERROR: Invalid JSON in {filepath.name}: {e}", file=sys.stderr)
                skipped += 1
            except Exception as e:
                print(f"  ERROR: Failed to import {filepath.name}: {e}", file=sys.stderr)
                skipped += 1

        return (imported, skipped)

    def get_summary(self) -> dict:
        """
        Return aggregate stats from the database.

        Returns:
            Dictionary with total_games, unique_players, date_range, top_players.
        """
        summary = {}

        with self.conn.cursor() as cur:
            # Total games
            cur.execute("SELECT COUNT(*) FROM games")
            summary["total_games"] = cur.fetchone()[0]

            # Unique players
            cur.execute("SELECT COUNT(DISTINCT player_name) FROM players")
            summary["unique_players"] = cur.fetchone()[0]

            # Date range
            cur.execute("SELECT MIN(timestamp), MAX(timestamp) FROM games")
            row = cur.fetchone()
            summary["date_min"] = row[0]
            summary["date_max"] = row[1]

            # Top players by total games, kills, deaths, K/D
            cur.execute(
                """
                SELECT
                    player_name,
                    COUNT(*) AS games,
                    COALESCE(SUM(kills), 0) AS total_kills,
                    COALESCE(SUM(deaths), 0) AS total_deaths,
                    CASE WHEN COALESCE(SUM(deaths), 0) > 0
                         THEN ROUND(CAST(SUM(kills) AS numeric) / SUM(deaths), 2)
                         ELSE 0 END AS kd
                FROM players
                GROUP BY player_name
                ORDER BY total_kills DESC
                LIMIT 20
                """
            )
            summary["top_players"] = []
            for row in cur.fetchall():
                summary["top_players"].append({
                    "name": row[0],
                    "games": row[1],
                    "kills": row[2],
                    "deaths": row[3],
                    "kd_ratio": float(row[4]),
                })

        return summary

    def close(self):
        """Close the database connection."""
        if self.conn and not self.conn.closed:
            self.conn.close()


def print_summary(summary: dict):
    """Print formatted summary to stdout."""
    print()
    print("=== Halo 2 Stats Summary ===")
    print(f"Total games: {summary['total_games']}")
    print(f"Unique players: {summary['unique_players']}")

    if summary.get("date_min") and summary.get("date_max"):
        date_min = summary["date_min"].strftime("%Y-%m-%d")
        date_max = summary["date_max"].strftime("%Y-%m-%d")
        print(f"Date range: {date_min} to {date_max}")

    top = summary.get("top_players", [])
    if top:
        print()
        print("Top Players:")
        for i, p in enumerate(top, 1):
            name = p["name"][:12].ljust(12)
            print(
                f"  {i:2d}. {name} - {p['games']} games, "
                f"{p['kills']} kills, {p['deaths']} deaths "
                f"(K/D: {p['kd_ratio']:.2f})"
            )

    print()


def main():
    parser = argparse.ArgumentParser(
        description="Export Halo 2 game history to PostgreSQL"
    )
    parser.add_argument(
        "--init-schema",
        action="store_true",
        help="Create database tables",
    )
    parser.add_argument(
        "--import-history",
        action="store_true",
        help="Import all JSON files from history dir",
    )
    parser.add_argument(
        "--import-file",
        help="Import a single JSON file",
    )
    parser.add_argument(
        "--summary",
        action="store_true",
        help="Print aggregate statistics",
    )
    parser.add_argument(
        "--history-dir",
        default="history",
        help="History directory (default: history/)",
    )
    parser.add_argument(
        "--db-url",
        help="PostgreSQL URL (default: DATABASE_URL env var)",
    )

    args = parser.parse_args()

    # Require at least one action
    if not any([args.init_schema, args.import_history, args.import_file, args.summary]):
        parser.print_help()
        sys.exit(1)

    # Check psycopg2 availability early
    if psycopg2 is None:
        print(
            "ERROR: psycopg2 is not installed.\n"
            "Install it with: pip install psycopg2-binary",
            file=sys.stderr,
        )
        sys.exit(1)

    db_url = args.db_url or os.environ.get("DATABASE_URL")
    if not db_url:
        print(
            "ERROR: No database URL. Set DATABASE_URL env var or use --db-url",
            file=sys.stderr,
        )
        sys.exit(1)

    try:
        db = Halo2Database(db_url)
    except Exception as e:
        print(f"ERROR: Failed to connect to database: {e}", file=sys.stderr)
        sys.exit(1)

    try:
        if args.init_schema:
            db.init_schema()

        if args.import_history:
            print(f"Importing from {args.history_dir}/...")
            imported, skipped = db.import_history_dir(args.history_dir)
            print(f"Done. Imported: {imported}, Skipped: {skipped}")

        if args.import_file:
            filepath = args.import_file
            if not os.path.isfile(filepath):
                print(f"ERROR: File not found: {filepath}", file=sys.stderr)
                sys.exit(1)
            with open(filepath, "r", encoding="utf-8") as f:
                snapshot = json.load(f)
            if db.import_snapshot(snapshot):
                print(f"Imported: {filepath}")
            else:
                print(f"Skipped (duplicate): {filepath}")

        if args.summary:
            summary = db.get_summary()
            print_summary(summary)

    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)
    finally:
        db.close()


if __name__ == "__main__":
    main()
