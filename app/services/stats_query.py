"""혼잡도 통계 조회. #24가 1분마다 쌓은 기록을 한국 시간 기준으로 묶어 평균을 낸다.

규칙은 공통 명세 4절을 따른다.
- 확인할 수 없는 분(장치 끊김, 전 좌석 확인 불가, 기록 없음)은 평균에서 뺀다.
- 평균은 소수 첫째 자리로 반올림(0.05는 올림)하고, 혼잡도는 반올림한 평균으로 정한다.
- 비율은 전체 좌석 기준이다.

    10:00~10:09  확인된 분 6개(빈자리 2,2,1,1,2,2), 장치 끊김 4개
    → 평균 빈자리 10/6 = 1.67 → 1.7, 1.7/4 = 42.5% → MODERATE

SQL은 기간만 거르고 묶기는 Python에서 한다. 하루 1,440줄, 8주여도 방 하나에 약 8만 줄이라 충분히 빠르고,
시간대 변환과 위 규칙을 한곳에서 읽을 수 있다.
"""

import asyncio
from collections import defaultdict
from collections.abc import Callable, Hashable, Iterable
from datetime import date, datetime, time, timedelta
from decimal import ROUND_HALF_UP, Decimal

from app.clock import SEOUL
from app.repositories.rooms import RoomRepository
from app.repositories.stats import RoomMinute, StatsStore
from app.schemas.stats import (
    DailyBucket,
    DailyStats,
    DataSource,
    WeeklyCell,
    WeeklyStats,
)
from app.services.reports import RoomNotFound
from app.services.rooms import congestion_level

DAILY_BUCKET_MINUTES = 10
WEEKLY_BUCKET_MINUTES = 60
MAX_WEEKS = 8
DEFAULT_WEEKS = 4
WEEKDAYS = ("MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN")


def is_observed(row: RoomMinute) -> bool:
    """확인된 분인가. 장치가 끊겼거나 모든 좌석을 확인할 수 없는 분은 평균에서 뺀다."""
    return row.edge_online and row.unknown_seats < row.total_seats


def round_half_up(value: Decimal) -> float:
    """소수 첫째 자리로 반올림한다. 내장 round()는 0.25를 0.2로 내리므로(은행가 반올림) 쓰지 않는다."""
    return float(value.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP))


def summarize_bucket(rows: list[RoomMinute], total_seats: int) -> dict:
    """한 칸에 속한 기록으로 평균을 낸다. rows에는 확인된 분만 들어 있다."""
    if not rows:
        return {"observed_minutes": 0, "avg_available_seats": None, "avg_unknown_seats": None,
                "congestion_level": None}
    n = len(rows)
    avg_available = round_half_up(Decimal(sum(row.available_seats for row in rows)) / n)
    avg_unknown = round_half_up(Decimal(sum(row.unknown_seats for row in rows)) / n)
    return {
        "observed_minutes": n,
        "avg_available_seats": avg_available,
        "avg_unknown_seats": avg_unknown,
        # 화면에 보이는 숫자(반올림한 평균)와 혼잡도 색이 어긋나지 않게, 반올림한 값으로 정한다.
        "congestion_level": congestion_level(avg_available, total_seats),
    }


def data_source(rows: Iterable[RoomMinute]) -> DataSource | None:
    """평균에 쓰인 확인된 분의 출처. 실제 기록과 예시 기록이 섞이면 MIXED, 확인된 분이 없으면 None."""
    sources = {row.source.value for row in rows}
    if not sources:
        return None
    return sources.pop() if len(sources) == 1 else "MIXED"


def group_observed(rows: Iterable[RoomMinute], key: Callable[[datetime], Hashable]) -> dict:
    """확인된 분만 골라 한국 시각 기준의 칸으로 묶는다."""
    groups: dict = defaultdict(list)
    for row in rows:
        if is_observed(row):
            groups[key(row.recorded_at.astimezone(SEOUL))].append(row)
    return groups


def kst_midnight(day: date) -> datetime:
    return datetime.combine(day, time(0), tzinfo=SEOUL)


def _total_seats(rooms: RoomRepository, room_id: str) -> int:
    room = rooms.find(room_id)
    if room is None:
        raise RoomNotFound(room_id)
    return len(room.config.seats)


async def daily_stats(rooms: RoomRepository, store: StatsStore, room_id: str, day: date) -> DailyStats:
    """한국 시간 하루(0시~24시)를 10분 묶음 144칸으로 나눈 평균."""
    total = _total_seats(rooms, room_id)
    start = kst_midnight(day)
    rows = await asyncio.to_thread(store.fetch, room_id, start, start + timedelta(days=1))

    groups = group_observed(rows, key=lambda at: (at.hour * 60 + at.minute) // DAILY_BUCKET_MINUTES)
    buckets = [
        DailyBucket(start=start + timedelta(minutes=index * DAILY_BUCKET_MINUTES),
                    **summarize_bucket(groups.get(index, []), total))
        for index in range(24 * 60 // DAILY_BUCKET_MINUTES)
    ]
    return DailyStats(
        room_id=room_id, date=day, bucket_minutes=DAILY_BUCKET_MINUTES, total_seats=total,
        data_source=data_source(row for group in groups.values() for row in group), buckets=buckets,
    )


async def weekly_stats(rooms: RoomRepository, store: StatsStore, room_id: str, *, today: date,
                       weeks: int) -> WeeklyStats:
    """어제까지 weeks×7일의 기록을 요일·1시간 168칸으로 묶은 평균. 기록이 덜 쌓인 오늘은 넣지 않는다."""
    total = _total_seats(rooms, room_id)
    start_date = today - timedelta(days=7 * weeks)
    rows = await asyncio.to_thread(store.fetch, room_id, kst_midnight(start_date), kst_midnight(today))

    groups = group_observed(rows, key=lambda at: (at.weekday(), at.hour))
    cells = []
    for weekday in range(7):
        for hour in range(24):
            cell_rows = groups.get((weekday, hour), [])
            observed_days = len({row.recorded_at.astimezone(SEOUL).date() for row in cell_rows})
            cells.append(WeeklyCell(weekday=WEEKDAYS[weekday], hour=hour, observed_days=observed_days,
                                    **summarize_bucket(cell_rows, total)))
    return WeeklyStats(
        room_id=room_id, start_date=start_date, end_date=today - timedelta(days=1), weeks=weeks,
        bucket_minutes=WEEKLY_BUCKET_MINUTES, total_seats=total,
        data_source=data_source(row for group in groups.values() for row in group), cells=cells,
    )
