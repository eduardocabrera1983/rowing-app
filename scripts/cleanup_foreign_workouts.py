"""One-off cleanup: remove workouts that don't belong to the owner.

Removes foreign-user workouts (and their stroke data) that were synced
before the owner-only login check existed, then refreshes sync_meta.

Usage (production, inside the Docker container):
    docker exec -it concept2-rowing-app python scripts/cleanup_foreign_workouts.py

Usage (local):
    python scripts/cleanup_foreign_workouts.py

The DB path comes from the DB_PATH env var (same as the app), and the
owner user ID from OWNER_USER_ID (defaults to the app's configured owner).
"""

import os
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from rowing_app.config import settings  # noqa: E402

DB_PATH = os.environ.get(
    "DB_PATH", str(Path(__file__).resolve().parent.parent / "workouts.db")
)
OWNER_ID = int(os.environ.get("OWNER_USER_ID", settings.owner_user_id))


def main() -> None:
    conn = sqlite3.connect(DB_PATH)
    try:
        users = conn.execute(
            "SELECT user_id, COUNT(*), ROUND(SUM(distance)/1000.0, 1) "
            "FROM workouts GROUP BY user_id"
        ).fetchall()
        print(f"DB: {DB_PATH}")
        print(f"Owner user_id: {OWNER_ID}")
        print("Before cleanup (user_id, workouts, km):")
        for u in users:
            marker = " <- owner" if u[0] == OWNER_ID else " <- FOREIGN, will be deleted"
            print(f"  {u}{marker}")

        cur = conn.execute("DELETE FROM workouts WHERE user_id != ?", (OWNER_ID,))
        deleted_workouts = cur.rowcount

        cur = conn.execute(
            "DELETE FROM stroke_data WHERE result_id NOT IN (SELECT id FROM workouts)"
        )
        deleted_strokes = cur.rowcount

        total = conn.execute("SELECT COUNT(*) FROM workouts").fetchone()[0]
        conn.execute("UPDATE sync_meta SET total_rows = ? WHERE id = 1", (total,))
        conn.commit()

        km, hrs = conn.execute(
            "SELECT ROUND(SUM(distance)/1000.0, 1), ROUND(SUM(time)/36000.0, 2) "
            "FROM workouts"
        ).fetchone()
        print(f"\nDeleted: {deleted_workouts} foreign workouts, "
              f"{deleted_strokes} orphan stroke rows")
        print(f"After cleanup: {total} workouts, {km} km, {hrs} hrs")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
