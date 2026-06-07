"""
Oura Ring v2 — fetch and normalize sleep + heart rate data.

Two ingestion paths:
  API:  fetch_and_normalize()  — requires OAuth2 tokens (scripts/oura_auth.py)
  CSV:  load_from_csv()        — drop files from Membership Hub into data/raw/oura/

Token storage: ~/.palms/oura_tokens.json
"""

import csv
import json
import time
from datetime import date, datetime
from pathlib import Path
from typing import Optional

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from palms.models import DailyHeartRate, SleepRecord

TOKEN_PATH = Path.home() / ".palms" / "oura_tokens.json"
BASE_URL = "https://api.ouraring.com/v2/usercollection"


def _load_tokens() -> dict:
    if not TOKEN_PATH.exists():
        raise FileNotFoundError(
            f"Oura tokens not found at {TOKEN_PATH}. Run scripts/oura_auth.py first."
        )
    return json.loads(TOKEN_PATH.read_text())


def _save_tokens(tokens: dict) -> None:
    TOKEN_PATH.parent.mkdir(parents=True, exist_ok=True)
    TOKEN_PATH.write_text(json.dumps(tokens, indent=2))


def _refresh_access_token(client_id: str, client_secret: str, refresh_token: str) -> dict:
    resp = httpx.post(
        "https://api.ouraring.com/oauth/token",
        data={
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "client_id": client_id,
            "client_secret": client_secret,
        },
    )
    resp.raise_for_status()
    tokens = resp.json()
    tokens["expires_at"] = int(time.time()) + tokens.get("expires_in", 86400)
    return tokens


def get_client(client_id: str, client_secret: str) -> httpx.Client:
    tokens = _load_tokens()
    if time.time() > tokens.get("expires_at", 0) - 300:
        tokens = _refresh_access_token(client_id, client_secret, tokens["refresh_token"])
        _save_tokens(tokens)
    return httpx.Client(
        headers={"Authorization": f"Bearer {tokens['access_token']}"},
        timeout=30,
    )


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
def _get_all_pages(client: httpx.Client, endpoint: str, params: dict) -> list[dict]:
    results = []
    next_token: Optional[str] = None
    while True:
        if next_token:
            params = {**params, "next_token": next_token}
        resp = client.get(f"{BASE_URL}/{endpoint}", params=params)
        resp.raise_for_status()
        body = resp.json()
        results.extend(body.get("data", []))
        next_token = body.get("next_token")
        if not next_token:
            break
    return results


def fetch_and_normalize(
    client_id: str,
    client_secret: str,
    start: date,
    end: date,
    raw_dir: Path,
) -> tuple[list[SleepRecord], list[DailyHeartRate]]:
    raw_dir.mkdir(parents=True, exist_ok=True)
    client = get_client(client_id, client_secret)
    params = {"start_date": str(start), "end_date": str(end)}

    raw_sleep = _get_all_pages(client, "sleep", params)
    (raw_dir / f"sleep_{start}_{end}.json").write_text(json.dumps(raw_sleep, indent=2))

    sleep_records = _normalize_sleep(raw_sleep)
    hr_records = _derive_daily_hr(raw_sleep)

    return sleep_records, hr_records


def _parse_dt(s: Optional[str]) -> Optional[datetime]:
    if not s:
        return None
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def _normalize_sleep(raw: list[dict]) -> list[SleepRecord]:
    records = []
    for item in raw:
        if item.get("type") not in ("long_sleep", "sleep"):
            continue
        day_str = item.get("day", "")
        try:
            day = date.fromisoformat(day_str)
        except ValueError:
            continue
        records.append(
            SleepRecord(
                source="oura",
                date=day,
                bedtime_start=_parse_dt(item.get("bedtime_start")),
                bedtime_end=_parse_dt(item.get("bedtime_end")),
                total_sleep_seconds=item.get("total_sleep_duration"),
                total_in_bed_seconds=item.get("time_in_bed"),
                sleep_efficiency=item.get("efficiency"),
                stage_deep_seconds=item.get("deep_sleep_duration"),
                stage_rem_seconds=item.get("rem_sleep_duration"),
                stage_light_seconds=item.get("light_sleep_duration"),
                stage_awake_seconds=item.get("awake_time"),
                avg_hrv_ms=item.get("average_hrv"),
                avg_hr_bpm=item.get("average_heart_rate"),
                min_hr_bpm=item.get("lowest_heart_rate"),
                sleep_score=item.get("score"),
                raw_source_id=item.get("id"),
            )
        )
    return records


def _derive_daily_hr(raw_sleep: list[dict]) -> list[DailyHeartRate]:
    """Derive resting HR from lowest overnight HR per sleep session."""
    by_date: dict[date, dict] = {}
    for item in raw_sleep:
        if item.get("type") not in ("long_sleep", "sleep"):
            continue
        try:
            day = date.fromisoformat(item["day"])
        except (KeyError, ValueError):
            continue
        by_date[day] = {
            "resting_hr_bpm": item.get("lowest_heart_rate"),
            "avg_hr_bpm": item.get("average_heart_rate"),
            "max_hr_bpm": None,
            "min_hr_bpm": item.get("lowest_heart_rate"),
        }
    return [
        DailyHeartRate(source="oura", date=d, **vals) for d, vals in by_date.items()
    ]


# ---------------------------------------------------------------------------
# CSV ingestion (Oura Membership Hub export)
# ---------------------------------------------------------------------------
# Drop CSV files from the export ZIP into data/raw/oura/ then run:
#   palms-ingest --source oura-csv

def load_from_csv(raw_dir: Path) -> tuple[list[SleepRecord], list[DailyHeartRate]]:
    """Parse all Oura CSV exports found in raw_dir.

    Auto-detects file type by header content. Sleep files produce SleepRecords;
    readiness files contribute resting HR to DailyHeartRate records.
    """
    sleep_records: list[SleepRecord] = []
    hr_records: list[DailyHeartRate] = []

    for path in sorted(raw_dir.glob("*.csv")):
        with path.open(newline="", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            headers = {h.lower() for h in (reader.fieldnames or [])}

        if "bedtimestart" in headers or "deepsleepstart" in headers or "deep_sleep_duration" in headers:
            sleep_records.extend(_parse_sleep_csv(path))
        elif "restingheartrate" in headers or "contributorsrestingheartrate" in headers:
            hr_records.extend(_parse_readiness_csv(path))

    # Also derive HR from sleep records if no readiness file present
    if sleep_records and not hr_records:
        hr_records = _derive_hr_from_sleep_records(sleep_records)

    return sleep_records, hr_records


def _col(row: dict, *candidates: str) -> Optional[str]:
    """Return first non-empty value from a list of possible column names (case-insensitive)."""
    lookup = {k.lower().replace(" ", "").replace("_", ""): v for k, v in row.items()}
    for c in candidates:
        val = lookup.get(c.lower().replace(" ", "").replace("_", ""))
        if val not in (None, ""):
            return val
    return None


def _to_int(v: Optional[str]) -> Optional[int]:
    try:
        return int(float(v)) if v else None
    except (ValueError, TypeError):
        return None


def _to_float(v: Optional[str]) -> Optional[float]:
    try:
        return float(v) if v else None
    except (ValueError, TypeError):
        return None


def _parse_sleep_csv(path: Path) -> list[SleepRecord]:
    records = []
    with path.open(newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            day_str = _col(row, "Day", "Date")
            if not day_str:
                continue
            try:
                day = date.fromisoformat(day_str[:10])
            except ValueError:
                continue

            records.append(SleepRecord(
                source="oura",
                date=day,
                bedtime_start=_parse_dt(_col(row, "BedtimeStart", "Bedtime_Start")),
                bedtime_end=_parse_dt(_col(row, "BedtimeEnd", "Bedtime_End")),
                total_sleep_seconds=_to_int(_col(row, "TotalSleepDuration", "Total_Sleep_Duration", "TotalSleep")),
                total_in_bed_seconds=_to_int(_col(row, "TimeInBed", "Time_In_Bed")),
                sleep_efficiency=_to_float(_col(row, "Efficiency")),
                stage_deep_seconds=_to_int(_col(row, "DeepSleepDuration", "Deep_Sleep_Duration")),
                stage_rem_seconds=_to_int(_col(row, "RemSleepDuration", "REM_Sleep_Duration", "RemSleep")),
                stage_light_seconds=_to_int(_col(row, "LightSleepDuration", "Light_Sleep_Duration", "LightSleep")),
                stage_awake_seconds=_to_int(_col(row, "AwakeTime", "Awake_Time")),
                avg_hrv_ms=_to_float(_col(row, "AverageHrv", "Average_HRV", "AverageHRV")),
                avg_hr_bpm=_to_float(_col(row, "AverageHeartRate", "Average_Heart_Rate")),
                min_hr_bpm=_to_float(_col(row, "LowestHeartRate", "Lowest_Heart_Rate")),
                sleep_score=_to_int(_col(row, "Score", "SleepScore", "Sleep_Score")),
                raw_source_id=_col(row, "ID", "Id", "SleepKey"),
            ))
    return records


def _parse_readiness_csv(path: Path) -> list[DailyHeartRate]:
    records = []
    with path.open(newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            day_str = _col(row, "Day", "Date")
            if not day_str:
                continue
            try:
                day = date.fromisoformat(day_str[:10])
            except ValueError:
                continue
            # ContributorsRestingHeartRate is a score (0-100), not BPM.
            # Use it only as a signal that the readiness file was found;
            # actual BPM comes from sleep data via _derive_hr_from_sleep_records.
            # If a future export includes actual BPM, it would appear here.
            resting_bpm = _to_float(_col(row, "RestingHeartRate", "Resting_Heart_Rate"))
            if resting_bpm and resting_bpm > 30:  # sanity check: score is 0-100, BPM > 30
                records.append(DailyHeartRate(
                    source="oura", date=day,
                    resting_hr_bpm=resting_bpm,
                    avg_hr_bpm=None, max_hr_bpm=None, min_hr_bpm=None,
                ))
    return records


def _derive_hr_from_sleep_records(sleep_records: list[SleepRecord]) -> list[DailyHeartRate]:
    return [
        DailyHeartRate(
            source="oura",
            date=r.date,
            resting_hr_bpm=r.min_hr_bpm,
            avg_hr_bpm=r.avg_hr_bpm,
            max_hr_bpm=None,
            min_hr_bpm=r.min_hr_bpm,
        )
        for r in sleep_records
        if r.min_hr_bpm or r.avg_hr_bpm
    ]
