from datetime import date
from typing import Literal

from pydantic import AwareDatetime, BaseModel

from app.schemas.rooms import CongestionLevel

DataSource = Literal["OBSERVED", "SEED", "MIXED"]
Weekday = Literal["MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"]


class StatsBucket(BaseModel):
    """여러 분을 묶은 한 칸의 평균. 확인된 분이 없으면 평균과 혼잡도가 null이다."""

    observed_minutes: int
    avg_available_seats: float | None
    avg_unknown_seats: float | None
    congestion_level: CongestionLevel | None


class DailyBucket(StatsBucket):
    start: AwareDatetime


class WeeklyCell(StatsBucket):
    weekday: Weekday
    hour: int
    observed_days: int


class DailyStats(BaseModel):
    room_id: str
    date: date
    bucket_minutes: int
    total_seats: int
    data_source: DataSource | None
    buckets: list[DailyBucket]


class WeeklyStats(BaseModel):
    room_id: str
    start_date: date
    end_date: date
    weeks: int
    bucket_minutes: int
    total_seats: int
    data_source: DataSource | None
    cells: list[WeeklyCell]
