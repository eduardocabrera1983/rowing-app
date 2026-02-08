"""SQLite storage with incremental sync for Concept2 workout data.

Design:
  - On first login the full history is fetched and stored locally.
  - On every subsequent dashboard visit the app checks the ``sync_meta``
    table.  If the last sync was >24 h ago it fetches only workouts
    *after* the most recent date already in the DB.
  - The dashboard always reads from the local DB → instant page loads.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from loguru import logger

from .api_client import Concept2Client
from .models import WorkoutResult

import os

# Default DB path – overridable via DB_PATH env var (used in Docker)
DB_PATH = Path(os.environ.get("DB_PATH", Path(__file__).resolve().parent.parent / "workouts.db"))

SYNC_INTERVAL = timedelta(hours=24)


# ──────────────────────────────────────────────
# Schema helpers
# ──────────────────────────────────────────────
def _get_connection(db_path: Path = DB_PATH) -> sqlite3.Connection:
    """Return a connection with Row factory for dict-like access."""
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db(db_path: Path = DB_PATH) -> None:
    """Create tables if they don't exist."""
    conn = _get_connection(db_path)
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS workouts (
            id              INTEGER PRIMARY KEY,
            user_id         INTEGER NOT NULL,
            date            TEXT NOT NULL,
            timezone        TEXT,
            date_utc        TEXT,
            distance        INTEGER NOT NULL,
            type            TEXT NOT NULL,
            time            INTEGER NOT NULL,
            time_formatted  TEXT,
            workout_type    TEXT,
            source          TEXT,
            weight_class    TEXT,
            verified        INTEGER,
            ranked          INTEGER,
            comments        TEXT,
            privacy         TEXT,
            stroke_rate     INTEGER,
            stroke_count    INTEGER,
            calories_total  INTEGER,
            drag_factor     INTEGER,
            heart_rate_avg  INTEGER,
            heart_rate_min  INTEGER,
            heart_rate_max  INTEGER,
            heart_rate_end  INTEGER,
            rest_time       INTEGER,
            rest_distance   INTEGER
        );

        CREATE TABLE IF NOT EXISTS sync_meta (
            id              INTEGER PRIMARY KEY CHECK (id = 1),
            last_sync_utc   TEXT NOT NULL,
            total_rows      INTEGER NOT NULL DEFAULT 0
        );

        CREATE INDEX IF NOT EXISTS idx_workouts_date ON workouts(date);
        """
    )
    conn.commit()
    conn.close()
    logger.debug("Database initialised.")


# ──────────────────────────────────────────────
# Write helpers
# ──────────────────────────────────────────────
def _upsert_workouts(conn: sqlite3.Connection, results: list[WorkoutResult]) -> int:
    """Insert or replace workouts. Returns count of rows written."""
    if not results:
        return 0

    rows = []
    for r in results:
        rows.append((
            r.id,
            r.user_id,
            r.date,
            r.timezone,
            r.date_utc,
            r.distance,
            r.type,
            r.time,
            r.time_formatted,
            r.workout_type,
            r.source,
            r.weight_class,
            1 if r.verified else 0 if r.verified is not None else None,
            1 if r.ranked else 0 if r.ranked is not None else None,
            r.comments,
            r.privacy,
            r.stroke_rate,
            r.stroke_count,
            r.calories_total,
            r.drag_factor,
            r.heart_rate.average if r.heart_rate else None,
            r.heart_rate.min if r.heart_rate else None,
            r.heart_rate.max if r.heart_rate else None,
            r.heart_rate.ending if r.heart_rate else None,
            r.rest_time,
            r.rest_distance,
        ))

    conn.executemany(
        """
        INSERT OR REPLACE INTO workouts (
            id, user_id, date, timezone, date_utc,
            distance, type, time, time_formatted,
            workout_type, source, weight_class,
            verified, ranked, comments, privacy,
            stroke_rate, stroke_count, calories_total, drag_factor,
            heart_rate_avg, heart_rate_min, heart_rate_max, heart_rate_end,
            rest_time, rest_distance
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        rows,
    )
    return len(rows)


def _update_sync_meta(conn: sqlite3.Connection) -> None:
    """Update the sync timestamp and row count."""
    now_utc = datetime.now(timezone.utc).isoformat()
    total = conn.execute("SELECT COUNT(*) FROM workouts").fetchone()[0]
    conn.execute(
        """
        INSERT INTO sync_meta (id, last_sync_utc, total_rows)
        VALUES (1, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
            last_sync_utc = excluded.last_sync_utc,
            total_rows = excluded.total_rows
        """,
        (now_utc, total),
    )


# ──────────────────────────────────────────────
# Read helpers
# ──────────────────────────────────────────────
def get_last_sync() -> Optional[datetime]:
    """Return the last sync timestamp (UTC) or None if never synced."""
    conn = _get_connection()
    row = conn.execute(
        "SELECT last_sync_utc FROM sync_meta WHERE id = 1"
    ).fetchone()
    conn.close()
    if row:
        return datetime.fromisoformat(row["last_sync_utc"])
    return None


def needs_sync() -> bool:
    """Return True if a sync is needed (never synced, or >24 h ago)."""
    last = get_last_sync()
    if last is None:
        return True
    elapsed = datetime.now(timezone.utc) - last
    return elapsed >= SYNC_INTERVAL


def get_latest_workout_date() -> Optional[str]:
    """Return the date string of the most recent workout in the DB."""
    conn = _get_connection()
    row = conn.execute(
        "SELECT date FROM workouts ORDER BY date DESC LIMIT 1"
    ).fetchone()
    conn.close()
    if row:
        return row["date"][:10]  # YYYY-MM-DD
    return None


def get_workout_count() -> int:
    """Return total number of workouts stored locally."""
    conn = _get_connection()
    count = conn.execute("SELECT COUNT(*) FROM workouts").fetchone()[0]
    conn.close()
    return count


def load_workouts_as_models(
    from_date: Optional[str] = None,
    to_date: Optional[str] = None,
) -> list[WorkoutResult]:
    """Load workouts from SQLite and return as WorkoutResult models.

    This is what the dashboard uses instead of calling the API.
    """
    conn = _get_connection()
    query = "SELECT * FROM workouts WHERE 1=1"
    params: list = []

    if from_date:
        query += " AND date >= ?"
        params.append(from_date)
    if to_date:
        query += " AND date <= ?"
        params.append(to_date + " 23:59:59")

    query += " ORDER BY date ASC"
    rows = conn.execute(query, params).fetchall()
    conn.close()

    results: list[WorkoutResult] = []
    for row in rows:
        hr_data = None
        if any(row[k] is not None for k in ("heart_rate_avg", "heart_rate_min",
                                              "heart_rate_max", "heart_rate_end")):
            from .models import HeartRate
            hr_data = HeartRate(
                average=row["heart_rate_avg"],
                min=row["heart_rate_min"],
                max=row["heart_rate_max"],
                ending=row["heart_rate_end"],
            )

        results.append(WorkoutResult(
            id=row["id"],
            user_id=row["user_id"],
            date=row["date"],
            timezone=row["timezone"],
            date_utc=row["date_utc"],
            distance=row["distance"],
            type=row["type"],
            time=row["time"],
            time_formatted=row["time_formatted"],
            workout_type=row["workout_type"],
            source=row["source"],
            weight_class=row["weight_class"],
            verified=bool(row["verified"]) if row["verified"] is not None else None,
            ranked=bool(row["ranked"]) if row["ranked"] is not None else None,
            comments=row["comments"],
            privacy=row["privacy"],
            stroke_rate=row["stroke_rate"],
            stroke_count=row["stroke_count"],
            calories_total=row["calories_total"],
            drag_factor=row["drag_factor"],
            heart_rate=hr_data,
            rest_time=row["rest_time"],
            rest_distance=row["rest_distance"],
        ))

    logger.info(f"Loaded {len(results)} workouts from local DB")
    return results


# ──────────────────────────────────────────────
# Sync logic
# ──────────────────────────────────────────────
async def sync_workouts(client: Concept2Client) -> dict:
    """Perform an incremental sync from the Concept2 API to SQLite.

    Returns a dict with sync metadata:
        - ``synced``: bool — whether a sync was performed
        - ``new_workouts``: int — number of new/updated workouts fetched
        - ``total_workouts``: int — total workouts in the DB
        - ``last_sync``: str — ISO timestamp of last sync
    """
    init_db()

    if not needs_sync():
        last = get_last_sync()
        total = get_workout_count()
        logger.info(
            f"Sync not needed — last sync {last.isoformat()} "
            f"({total} workouts in DB)"
        )
        return {
            "synced": False,
            "new_workouts": 0,
            "total_workouts": total,
            "last_sync": last.isoformat() if last else None,
        }

    # Determine what to fetch
    latest_date = get_latest_workout_date()

    if latest_date is None:
        # First sync — full historical fetch
        logger.info("First sync: fetching full workout history…")
        results = await client.get_all_results(workout_type="rower")
    else:
        # Incremental: fetch from the day after the latest workout
        # We use the latest date (not latest+1day) to catch any late updates
        logger.info(f"Incremental sync: fetching workouts from {latest_date}…")
        results = await client.get_all_results(
            from_date=latest_date,
            workout_type="rower",
        )

    # Write to DB
    conn = _get_connection()
    new_count = _upsert_workouts(conn, results)
    _update_sync_meta(conn)
    conn.commit()
    total = conn.execute("SELECT COUNT(*) FROM workouts").fetchone()[0]
    conn.close()

    last_sync = get_last_sync()
    logger.info(
        f"Sync complete: {new_count} workouts written, "
        f"{total} total in DB."
    )

    return {
        "synced": True,
        "new_workouts": new_count,
        "total_workouts": total,
        "last_sync": last_sync.isoformat() if last_sync else None,
    }
