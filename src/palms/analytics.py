import sqlite3

import numpy as np
import pandas as pd


def _source_priority_hr(df: pd.DataFrame) -> pd.DataFrame:
    """When multiple sources have data for the same date, prefer Oura > Garmin > Apple."""
    priority = {"oura": 0, "garmin": 1, "apple_health": 2}
    df = df.copy()
    df["_p"] = df["source"].map(priority).fillna(99)
    df = df.sort_values(["date", "_p"]).drop_duplicates(subset="date", keep="first")
    return df.drop(columns="_p").reset_index(drop=True)


def get_resting_hr_trend(conn: sqlite3.Connection, days: int = 90) -> pd.DataFrame:
    df = pd.read_sql(
        f"""
        SELECT date, source, resting_hr_bpm
        FROM daily_heart_rate
        WHERE resting_hr_bpm IS NOT NULL
          AND date >= date('now', '-{days} days')
        ORDER BY date
        """,
        conn,
        parse_dates=["date"],
    )
    return _source_priority_hr(df)


def get_resting_hr_stats(conn: sqlite3.Connection, days: int = 30) -> dict:
    df = get_resting_hr_trend(conn, days)
    if df.empty:
        return {}
    vals = df["resting_hr_bpm"].dropna()
    trend = "flat"
    if len(vals) >= 7:
        x = np.arange(len(vals))
        slope = np.polyfit(x, vals, 1)[0]
        if slope > 0.05:
            trend = "rising"
        elif slope < -0.05:
            trend = "falling"
    return {
        "mean": round(vals.mean(), 1),
        "min": round(vals.min(), 1),
        "max": round(vals.max(), 1),
        "trend": trend,
        "days": len(vals),
    }


def get_sleep_trend(conn: sqlite3.Connection, days: int = 30) -> pd.DataFrame:
    df = pd.read_sql(
        f"""
        SELECT date, source,
               total_sleep_seconds / 3600.0 AS sleep_hours,
               stage_deep_seconds, stage_rem_seconds,
               stage_light_seconds, stage_awake_seconds,
               sleep_score,
               bedtime_start
        FROM sleep_records
        WHERE total_sleep_seconds IS NOT NULL
          AND date >= date('now', '-{days} days')
        ORDER BY date
        """,
        conn,
        parse_dates=["date", "bedtime_start"],
    )
    if df.empty:
        return df
    priority = {"oura": 0, "garmin": 1, "apple_health": 2}
    df["_p"] = df["source"].map(priority).fillna(99)
    df = df.sort_values(["date", "_p"]).drop_duplicates(subset="date", keep="first")
    return df.drop(columns="_p").reset_index(drop=True)


def get_sleep_stats(conn: sqlite3.Connection, days: int = 30) -> dict:
    df = get_sleep_trend(conn, days)
    if df.empty:
        return {}
    hrs = df["sleep_hours"].dropna()
    stats: dict = {
        "avg_hours": round(hrs.mean(), 2),
        "min_hours": round(hrs.min(), 2),
        "max_hours": round(hrs.max(), 2),
        "days": len(hrs),
    }
    bedtimes = df["bedtime_start"].dropna()
    if len(bedtimes) >= 3:
        minutes = bedtimes.dt.hour * 60 + bedtimes.dt.minute
        stats["bedtime_consistency_min"] = round(float(minutes.std()), 1)
    return stats


def get_weight_trend(conn: sqlite3.Connection, days: int = 90) -> pd.DataFrame:
    return pd.read_sql(
        f"""
        SELECT date, weight_kg, fat_percentage
        FROM daily_weight
        WHERE weight_kg IS NOT NULL
          AND date >= date('now', '-{days} days')
        ORDER BY date
        """,
        conn,
        parse_dates=["date"],
    )


def get_weight_stats(conn: sqlite3.Connection, days: int = 30) -> dict:
    df = get_weight_trend(conn, days)
    if df.empty:
        return {}
    w = df["weight_kg"].dropna()
    stats: dict = {
        "avg_kg": round(w.mean(), 1),
        "min_kg": round(w.min(), 1),
        "max_kg": round(w.max(), 1),
        "days": len(w),
    }
    fat = df["fat_percentage"].dropna()
    if not fat.empty:
        stats["avg_fat_pct"] = round(fat.mean(), 1)
    trend = "flat"
    if len(w) >= 7:
        slope = np.polyfit(np.arange(len(w)), w, 1)[0]
        if slope > 0.02:
            trend = "rising"
        elif slope < -0.02:
            trend = "falling"
    stats["trend"] = trend
    return stats
