"""혼잡도 기록. 서버가 켜져 있는 동안 1분마다 방 요약을 SQLite에 남긴다.

    13:50:20  서버 시작 → 아직 기록한 분이 없음 → 13:50 기록
    13:50:21 ~ 13:50:59  같은 분 → 건너뜀
    13:51:00.4  분이 바뀜 → 13:51 기록

기록에는 그 순간의 사실(장치 끊김, 전 좌석 확인 불가 포함)을 그대로 남긴다.
평균에서 뺄 분을 고르는 해석은 조회(#25)가 맡는다. 기록 단계에서 거르면 나중에 규칙을 바꿀 수 없다.
"""

import asyncio
import logging
from datetime import datetime

from app.clock import Clock
from app.repositories.rooms import RoomRepository
from app.repositories.stats import RoomMinute, StatsStore, floor_minute
from app.services.rooms import summarize

logger = logging.getLogger(__name__)

CHECK_INTERVAL_SECONDS = 1.0
"""분이 바뀌었는지 확인하는 주기. 기록은 분이 바뀐 뒤 최대 이만큼 늦게 남는다."""


async def snapshot_rooms(rooms: RoomRepository, minute: datetime) -> list[RoomMinute]:
    """모든 방의 지금 요약을 읽는다. 조회 응답과 같은 summarize()로 계산한다."""
    rows = []
    for room in rooms.all():
        # 방 상태는 잠금 안에서 읽는다는 규칙을 지킨다. 숫자만 복사하고 바로 놓는다.
        async with room.lock:
            summary = summarize(room)
            edge_online = room.edge_online
        rows.append(RoomMinute(
            room_id=room.config.room_id, recorded_at=minute, total_seats=summary.total_seats,
            available_seats=summary.available_seats, unknown_seats=summary.unknown_seats,
            edge_online=edge_online,
        ))
    return rows


async def record_minute(rooms: RoomRepository, store: StatsStore, minute: datetime) -> int:
    """minute에 해당하는 방 요약을 기록하고, 새로 들어간 줄 수를 돌려준다."""
    rows = await snapshot_rooms(rooms, minute)
    # 디스크 쓰기는 잠금 밖, 별도 스레드에서 한다. 그동안에도 장치 보고와 알림은 계속 처리된다.
    return await asyncio.to_thread(store.insert, rows)


async def record_every_minute(rooms: RoomRepository, store: StatsStore, *, clock: Clock,
                              interval: float = CHECK_INTERVAL_SECONDS) -> None:
    """interval초마다 분이 바뀌었는지 보고, 바뀌었으면 기록한다. lifespan에서 백그라운드 작업으로 띄운다.

    sleep(60)을 반복하면 처리 시간만큼 밀리다가 어느 분을 통째로 건너뛴다. 짧은 주기로 시계를 보면
    밀리지 않고, 테스트에서는 주입한 시계만 옮기면 된다.
    """
    last_minute: datetime | None = None
    while True:
        minute = floor_minute(clock())
        if last_minute is None or minute > last_minute:
            # 실패해도 이 분은 넘어간다. 다음 분에 다시 시도하고, 같은 오류를 1초마다 남기지 않는다.
            last_minute = minute
            try:
                await record_minute(rooms, store, minute)
            except Exception:
                # 기록이 실패해도 서버(좌석 안내)는 계속 돈다.
                logger.exception("혼잡도 기록 실패: %s", minute.isoformat())
        await asyncio.sleep(interval)
