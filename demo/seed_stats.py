"""시연용 혼잡도 예시 기록을 만든다.

    uv run python -m demo.seed_stats            # 어제까지 28일치
    uv run python -m demo.seed_stats --days 7

시연 날에는 실제 기록이 몇 시간치뿐이라 요일·시간대별 평균을 채울 수 없다. 이 스크립트가 지난 날짜의
기록을 source=SEED로 만들어, 화면과 발표에서 예시 데이터임을 밝힐 수 있게 한다.

- 오늘은 넣지 않는다. 오늘 그래프는 실제 기록으로만 그린다.
- 이미 기록이 있는 방·분은 건너뛴다. 몇 번을 돌려도 실제 기록을 덮어쓰지 않는다.
- 같은 방·날짜에는 항상 같은 기록이 나온다(난수 시드 고정).
"""

import argparse
import os
import random
from collections.abc import Iterator
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path

from app.clock import SEOUL
from app.models.rooms import RoomConfig
from app.repositories.rooms import ROOMS_CONFIG_PATH, RoomsFile
from app.repositories.stats import RecordSource, RoomMinute, StatsStore
from app.settings import DEFAULT_STATS_DB_PATH

DEFAULT_DAYS = 28
"""요일·시간대별 평균의 기본 조회 기간(4주)을 채우는 양."""

DEVICE_HOURS = range(8, 22)
"""장치를 켜 두는 시간(한국 시간 8시~22시 전). 밤에는 장치 끊김으로 남겨, 그래프의 빈 구간을 시연한다."""


def busy_ratio(day: date, hour: int) -> float:
    """그 시간대에 자리가 차 있는 비율의 기준값. 평일 수업 시간은 붐비고 점심과 주말은 한산하다."""
    if day.weekday() >= 5:
        return 0.2 if 10 <= hour < 18 else 0.1
    if hour < 10:
        return 0.3
    if hour < 12:
        return 0.75
    if hour < 13:
        return 0.45
    if hour < 17:
        return 0.8
    if hour < 19:
        return 0.55
    return 0.35


def day_rows(config: RoomConfig, day: date) -> Iterator[RoomMinute]:
    """한 방의 하루(한국 시간 0시~24시) 1,440분 기록. 상태는 10분마다 바뀐다."""
    rng = random.Random(f"{config.room_id}:{day.isoformat()}")
    total = len(config.seats)
    start = datetime.combine(day, time(0), tzinfo=SEOUL)
    for block in range(144):
        block_start = start + timedelta(minutes=10 * block)
        if block_start.hour not in DEVICE_HOURS:
            available, unknown, online = 0, total, False
        else:
            busy = round(total * busy_ratio(day, block_start.hour) + rng.gauss(0, 0.6))
            unknown = 1 if rng.random() < 0.05 else 0  # 가끔 한 좌석이 가려진다
            busy = min(max(busy, 0), total - unknown)
            available, online = total - busy - unknown, True
        for minute in range(10):
            yield RoomMinute(
                room_id=config.room_id,
                recorded_at=(block_start + timedelta(minutes=minute)).astimezone(UTC),
                total_seats=total, available_seats=available, unknown_seats=unknown,
                edge_online=online, source=RecordSource.SEED,
            )


def seed_rows(configs: tuple[RoomConfig, ...], *, today: date, days: int) -> list[RoomMinute]:
    """today 전날부터 거슬러 days일치 예시 기록. today는 한국 시간 기준 날짜다."""
    return [
        row
        for offset in range(days, 0, -1)
        for config in configs
        for row in day_rows(config, today - timedelta(days=offset))
    ]


def main() -> None:
    parser = argparse.ArgumentParser(description="시연용 혼잡도 예시 기록(source=SEED)을 만든다.")
    parser.add_argument("--days", type=int, default=DEFAULT_DAYS, help=f"만들 날 수 (기본 {DEFAULT_DAYS})")
    parser.add_argument("--db", type=Path, default=Path(os.environ.get("STATS_DB_PATH", DEFAULT_STATS_DB_PATH)),
                        help="기록 파일 경로 (기본: 환경 변수 STATS_DB_PATH, 없으면 var/stats.sqlite3)")
    args = parser.parse_args()

    configs = RoomsFile.model_validate_json(ROOMS_CONFIG_PATH.read_bytes()).rooms
    today = datetime.now(SEOUL).date()
    rows = seed_rows(configs, today=today, days=args.days)

    store = StatsStore(args.db)
    store.create_schema()
    inserted = store.insert(rows)
    first = today - timedelta(days=args.days)
    print(f"{args.db}: {first} ~ {today - timedelta(days=1)} 예시 기록 {inserted}줄을 넣었습니다."
          f" (이미 있던 {len(rows) - inserted}줄은 건너뜀)")


if __name__ == "__main__":
    main()
