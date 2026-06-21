"""
Withings scale — fetch and normalize body composition measurements.

Token storage: ~/.palms/withings_tokens.json
Run scripts/withings_auth.py once to populate tokens.

Measure types fetched: weight (1), fat mass kg (6), fat ratio % (8),
muscle mass kg (76), bone mass kg (88), hydration kg (77).
"""

import json
import time
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Optional

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from palms.models import DailyWeight

TOKEN_PATH = Path.home() / ".palms" / "withings_tokens.json"
MEASURE_URL = "https://wbsapi.withings.net/measure"
TOKEN_URL = "https://wbsapi.withings.net/v2/oauth2"

MEAS_TYPES = "1,6,8,76,88,77"
TYPE_MAP = {1: "weight_kg", 6: "fat_mass_kg", 8: "fat_percentage",
            76: "muscle_mass_kg", 88: "bone_mass_kg", 77: "hydration_kg"}


def _load_tokens() -> dict:
    if not TOKEN_PATH.exists():
        raise FileNotFoundError(
            f"Withings tokens not found at {TOKEN_PATH}. Run scripts/withings_auth.py first."
        )
    return json.loads(TOKEN_PATH.read_text())


def _save_tokens(tokens: dict) -> None:
    TOKEN_PATH.parent.mkdir(parents=True, exist_ok=True)
    TOKEN_PATH.write_text(json.dumps(tokens, indent=2))


def _refresh_access_token(client_id: str, client_secret: str, refresh_token: str) -> dict:
    resp = httpx.post(TOKEN_URL, data={
        "action": "requesttoken",
        "grant_type": "refresh_token",
        "client_id": client_id,
        "client_secret": client_secret,
        "refresh_token": refresh_token,
    })
    resp.raise_for_status()
    body = resp.json()
    if body.get("status") != 0:
        raise RuntimeError(f"Withings token refresh failed: {body}")
    tokens = body["body"]
    tokens["expires_at"] = int(time.time()) + tokens.get("expires_in", 10800)
    return tokens


def _get_client(client_id: str, client_secret: str) -> httpx.Client:
    tokens = _load_tokens()
    if time.time() > tokens.get("expires_at", 0) - 300:
        tokens = _refresh_access_token(client_id, client_secret, tokens["refresh_token"])
        _save_tokens(tokens)
    return httpx.Client(
        headers={"Authorization": f"Bearer {tokens['access_token']}"},
        timeout=30,
    )


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
def _fetch_measures(client: httpx.Client, start: date, end: date) -> list[dict]:
    resp = client.get(MEASURE_URL, params={
        "action": "getmeas",
        "meastype": MEAS_TYPES,
        "category": 1,
        "startdate": int(datetime(start.year, start.month, start.day, tzinfo=timezone.utc).timestamp()),
        "enddate": int(datetime(end.year, end.month, end.day, 23, 59, 59, tzinfo=timezone.utc).timestamp()),
    })
    resp.raise_for_status()
    body = resp.json()
    if body.get("status") != 0:
        raise RuntimeError(f"Withings API error: {body}")
    return body["body"]["measuregrps"]


def fetch_and_normalize(
    client_id: str,
    client_secret: str,
    start: date,
    end: date,
    raw_dir: Path,
) -> list[DailyWeight]:
    raw_dir.mkdir(parents=True, exist_ok=True)
    client = _get_client(client_id, client_secret)
    groups = _fetch_measures(client, start, end)
    (raw_dir / f"measures_{start}_{end}.json").write_text(json.dumps(groups, indent=2))
    return _normalize(groups)


def _decode(value: int, unit: int) -> float:
    return value * (10 ** unit)


def _normalize(groups: list[dict]) -> list[DailyWeight]:
    by_date: dict[date, dict] = {}
    for grp in groups:
        day = datetime.fromtimestamp(grp["date"], tz=timezone.utc).date()
        entry = by_date.setdefault(day, {})
        for m in grp.get("measures", []):
            field = TYPE_MAP.get(m["type"])
            if field and field not in entry:
                entry[field] = round(_decode(m["value"], m["unit"]), 2)

    records = []
    for day, entry in sorted(by_date.items()):
        weight_kg = entry.get("weight_kg")
        hydration_kg = entry.get("hydration_kg")
        water_pct: Optional[float] = None
        if hydration_kg and weight_kg:
            water_pct = round(hydration_kg / weight_kg * 100, 1)
        records.append(DailyWeight(
            source="withings",
            date=day,
            weight_kg=weight_kg,
            fat_mass_kg=entry.get("fat_mass_kg"),
            fat_percentage=entry.get("fat_percentage"),
            muscle_mass_kg=entry.get("muscle_mass_kg"),
            bone_mass_kg=entry.get("bone_mass_kg"),
            water_percentage=water_pct,
        ))
    return records
