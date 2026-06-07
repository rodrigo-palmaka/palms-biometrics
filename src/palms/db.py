import sqlite3
from pathlib import Path
from typing import Sequence

from palms.models import DailyHeartRate, SleepRecord

SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS sources (
    id           TEXT PRIMARY KEY,
    display_name TEXT NOT NULL,
    last_synced_at TIMESTAMP
);

CREATE TABLE IF NOT EXISTS sleep_records (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    source               TEXT NOT NULL REFERENCES sources(id),
    date                 DATE NOT NULL,
    bedtime_start        TIMESTAMP,
    bedtime_end          TIMESTAMP,
    total_sleep_seconds  INTEGER,
    total_in_bed_seconds INTEGER,
    sleep_efficiency     REAL,
    stage_deep_seconds   INTEGER,
    stage_rem_seconds    INTEGER,
    stage_light_seconds  INTEGER,
    stage_awake_seconds  INTEGER,
    avg_hrv_ms           REAL,
    avg_hr_bpm           REAL,
    min_hr_bpm           REAL,
    sleep_score          INTEGER,
    raw_source_id        TEXT,
    ingested_at          TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(source, date, raw_source_id)
);

CREATE INDEX IF NOT EXISTS idx_sleep_date ON sleep_records(date);

CREATE TABLE IF NOT EXISTS daily_heart_rate (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    source         TEXT NOT NULL REFERENCES sources(id),
    date           DATE NOT NULL,
    resting_hr_bpm REAL,
    avg_hr_bpm     REAL,
    max_hr_bpm     REAL,
    min_hr_bpm     REAL,
    ingested_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(source, date)
);

CREATE INDEX IF NOT EXISTS idx_hr_date ON daily_heart_rate(date);

CREATE TABLE IF NOT EXISTS ingestion_log (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    source           TEXT NOT NULL,
    run_at           TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    start_date       DATE,
    end_date         DATE,
    records_inserted INTEGER,
    status           TEXT,
    error_msg        TEXT
);
"""

SOURCES = {
    "oura":         "Oura Ring",
    "garmin":       "Garmin Connect",
    "apple_health": "Apple Health",
    "strava":       "Strava",
}


def get_connection(db_path: str) -> sqlite3.Connection:
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    for source_id, display_name in SOURCES.items():
        conn.execute(
            "INSERT OR IGNORE INTO sources (id, display_name) VALUES (?, ?)",
            (source_id, display_name),
        )
    conn.commit()
    return conn


def upsert_sleep_records(conn: sqlite3.Connection, records: Sequence[SleepRecord]) -> int:
    rows = [
        (
            r.source, str(r.date),
            r.bedtime_start.isoformat() if r.bedtime_start else None,
            r.bedtime_end.isoformat() if r.bedtime_end else None,
            r.total_sleep_seconds, r.total_in_bed_seconds, r.sleep_efficiency,
            r.stage_deep_seconds, r.stage_rem_seconds,
            r.stage_light_seconds, r.stage_awake_seconds,
            r.avg_hrv_ms, r.avg_hr_bpm, r.min_hr_bpm,
            r.sleep_score, r.raw_source_id,
        )
        for r in records
    ]
    conn.executemany(
        """INSERT OR IGNORE INTO sleep_records
           (source, date, bedtime_start, bedtime_end,
            total_sleep_seconds, total_in_bed_seconds, sleep_efficiency,
            stage_deep_seconds, stage_rem_seconds, stage_light_seconds, stage_awake_seconds,
            avg_hrv_ms, avg_hr_bpm, min_hr_bpm, sleep_score, raw_source_id)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        rows,
    )
    conn.commit()
    return len(rows)


def upsert_daily_hr(conn: sqlite3.Connection, records: Sequence[DailyHeartRate]) -> int:
    rows = [
        (r.source, str(r.date), r.resting_hr_bpm, r.avg_hr_bpm, r.max_hr_bpm, r.min_hr_bpm)
        for r in records
    ]
    conn.executemany(
        """INSERT OR IGNORE INTO daily_heart_rate
           (source, date, resting_hr_bpm, avg_hr_bpm, max_hr_bpm, min_hr_bpm)
           VALUES (?,?,?,?,?,?)""",
        rows,
    )
    conn.commit()
    return len(rows)


def log_ingestion(
    conn: sqlite3.Connection,
    source: str,
    start_date,
    end_date,
    records_inserted: int,
    status: str,
    error_msg: str = None,
) -> None:
    conn.execute(
        """INSERT INTO ingestion_log
           (source, start_date, end_date, records_inserted, status, error_msg)
           VALUES (?,?,?,?,?,?)""",
        (source, str(start_date), str(end_date), records_inserted, status, error_msg),
    )
    conn.execute(
        "UPDATE sources SET last_synced_at = CURRENT_TIMESTAMP WHERE id = ?", (source,)
    )
    conn.commit()
