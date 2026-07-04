"""
Persistent history storage using SQLite.
Stores temperature and fan RPM readings with configurable retention.
"""

import logging
import sqlite3
import time
from pathlib import Path
from typing import Optional

logger = logging.getLogger("fnos-fan.history")

DB_DIR = Path("/var/lib/fnos-fan-control")
DB_PATH = DB_DIR / "history.db"


def _get_db() -> sqlite3.Connection:
    DB_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    return conn


def init_db():
    conn = _get_db()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS temperature_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sensor_name TEXT NOT NULL,
            value REAL NOT NULL,
            timestamp REAL NOT NULL
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS fan_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            fan_name TEXT NOT NULL,
            pwm INTEGER NOT NULL,
            rpm INTEGER NOT NULL,
            timestamp REAL NOT NULL
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_temp_time ON temperature_history(timestamp)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_temp_name ON temperature_history(sensor_name)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_fan_time ON fan_history(timestamp)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_fan_name ON fan_history(fan_name)")
    conn.commit()
    conn.close()
    logger.info(f"History DB initialized at {DB_PATH}")


def write_temperature(sensor_name: str, value: float, timestamp: Optional[float] = None):
    if timestamp is None:
        timestamp = time.time()
    conn = _get_db()
    conn.execute(
        "INSERT INTO temperature_history (sensor_name, value, timestamp) VALUES (?, ?, ?)",
        (sensor_name, value, timestamp),
    )
    conn.commit()
    conn.close()


def write_fan_state(fan_name: str, pwm: int, rpm: int, timestamp: Optional[float] = None):
    if timestamp is None:
        timestamp = time.time()
    conn = _get_db()
    conn.execute(
        "INSERT INTO fan_history (fan_name, pwm, rpm, timestamp) VALUES (?, ?, ?, ?)",
        (fan_name, pwm, rpm, timestamp),
    )
    conn.commit()
    conn.close()


def read_temperature_history(
    sensor_name: Optional[str] = None,
    days: int = 7,
    limit: int = 5000,
) -> list[dict]:
    cutoff = time.time() - days * 86400
    conn = _get_db()
    if sensor_name:
        rows = conn.execute(
            "SELECT sensor_name, value, timestamp FROM temperature_history "
            "WHERE timestamp > ? AND sensor_name = ? ORDER BY timestamp DESC LIMIT ?",
            (cutoff, sensor_name, limit),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT sensor_name, value, timestamp FROM temperature_history "
            "WHERE timestamp > ? ORDER BY timestamp DESC LIMIT ?",
            (cutoff, limit),
        ).fetchall()
    conn.close()
    return [{"sensor": r[0], "value": r[1], "timestamp": r[2]} for r in rows]


def read_fan_history(
    fan_name: Optional[str] = None,
    days: int = 7,
    limit: int = 5000,
) -> list[dict]:
    cutoff = time.time() - days * 86400
    conn = _get_db()
    if fan_name:
        rows = conn.execute(
            "SELECT fan_name, pwm, rpm, timestamp FROM fan_history "
            "WHERE timestamp > ? AND fan_name = ? ORDER BY timestamp DESC LIMIT ?",
            (cutoff, fan_name, limit),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT fan_name, pwm, rpm, timestamp FROM fan_history "
            "WHERE timestamp > ? ORDER BY timestamp DESC LIMIT ?",
            (cutoff, limit),
        ).fetchall()
    conn.close()
    return [{"fan": r[0], "pwm": r[1], "rpm": r[2], "timestamp": r[3]} for r in rows]


def get_temp_summary(days: int = 1) -> dict:
    """Get min/max/avg temps for each sensor in the last N days."""
    cutoff = time.time() - days * 86400
    conn = _get_db()
    rows = conn.execute(
        "SELECT sensor_name, MIN(value), MAX(value), AVG(value) FROM temperature_history "
        "WHERE timestamp > ? GROUP BY sensor_name",
        (cutoff,),
    ).fetchall()
    conn.close()
    return {r[0]: {"min": round(r[1], 1), "max": round(r[2], 1), "avg": round(r[3], 1)} for r in rows}


def cleanup_old_records(retention_days: int):
    cutoff = time.time() - retention_days * 86400
    conn = _get_db()
    deleted_temp = conn.execute(
        "DELETE FROM temperature_history WHERE timestamp < ?", (cutoff,)
    ).rowcount
    deleted_fan = conn.execute(
        "DELETE FROM fan_history WHERE timestamp < ?", (cutoff,)
    ).rowcount
    conn.commit()
    conn.close()
    if deleted_temp or deleted_fan:
        logger.info(f"Cleaned up history: {deleted_temp} temps, {deleted_fan} fan records older than {retention_days}d")
