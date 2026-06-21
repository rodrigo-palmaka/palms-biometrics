from dataclasses import dataclass
from datetime import date, datetime
from typing import Optional


@dataclass
class SleepRecord:
    source: str
    date: date
    bedtime_start: Optional[datetime]
    bedtime_end: Optional[datetime]
    total_sleep_seconds: Optional[int]
    total_in_bed_seconds: Optional[int]
    sleep_efficiency: Optional[float]   # 0–100
    stage_deep_seconds: Optional[int]
    stage_rem_seconds: Optional[int]
    stage_light_seconds: Optional[int]
    stage_awake_seconds: Optional[int]
    avg_hrv_ms: Optional[float]
    avg_hr_bpm: Optional[float]
    min_hr_bpm: Optional[float]
    sleep_score: Optional[int]
    raw_source_id: Optional[str]


@dataclass
class DailyHeartRate:
    source: str
    date: date
    resting_hr_bpm: Optional[float]
    avg_hr_bpm: Optional[float]
    max_hr_bpm: Optional[float]
    min_hr_bpm: Optional[float]


@dataclass
class DailyWeight:
    source: str
    date: date
    weight_kg: Optional[float]
    fat_mass_kg: Optional[float]
    fat_percentage: Optional[float]
    muscle_mass_kg: Optional[float]
    bone_mass_kg: Optional[float]
    water_percentage: Optional[float]
