"""장치 연결 감시. 장치가 보고를 멈추면 그 방을 확인 불가로 바꾼다.

    10:15:40  마지막 보고 수신 (room.last_report_at)
    10:16:10  아직 30초 전 → 그대로
    10:16:11  30초 넘음 → 오프라인 전환: 전 좌석 UNKNOWN·EDGE_OFFLINE, 알림 전송
    10:16:12  이미 오프라인 → 건너뜀 (같은 알림을 반복하지 않음)
"""

import asyncio
import logging
from datetime import timedelta

from app.clock import Clock
from app.models.rooms import RoomState, SeatReason, SeatStatus
from app.repositories.rooms import RoomRepository
from app.services.events import Publish, room_events

logger = logging.getLogger(__name__)

OFFLINE_AFTER = timedelta(seconds=30)
"""마지막 보고를 받은 뒤 이만큼 지나면 장치가 끊긴 것으로 본다."""

CHECK_INTERVAL_SECONDS = 1.0
"""감시 작업이 방들을 확인하는 주기. 끊김은 30초에서 최대 이만큼 늦게 발견된다."""


async def mark_offline_if_silent(room: RoomState, *, clock: Clock, publish: Publish) -> bool:
    """마지막 보고 후 30초가 지났으면 방을 오프라인으로 바꾸고 알린다. 바꿨으면 True."""
    async with room.lock:
        # 판단 시각은 잠금을 잡은 뒤에 읽는다. 잠금을 기다리는 사이 보고가 반영됐다면 그 보고까지 보고 판단한다.
        now = clock()

        # 1. 이미 오프라인이면 아무것도 하지 않는다. 서버 시작 직후의 방도 여기에 해당한다.
        if not room.edge_online or room.last_report_at is None:
            return False

        # 2. 30초가 안 됐으면 그대로 둔다. 서버가 보고를 받은 시각으로만 잰다(장치 시계는 쓰지 않는다).
        if now - room.last_report_at < OFFLINE_AFTER:
            return False

        # 3. 전 좌석을 확인 불가로 바꾼다. 마지막 확인 시각은 그대로, 상태 변경 시각은 지금(서버 전환 시각).
        next_states = {
            seat_id: state.transition(
                status=SeatStatus.UNKNOWN, reason=SeatReason.EDGE_OFFLINE, observed_at=None, at=now
            )
            for seat_id, state in room.seats.items()
        }
        changes = room.replace_seats(next_states)
        room.edge_online = False
        room.version += 1

        # 4. 알림도 잠금 안에서 보낸다. 보고 반영과 같은 이유로, 웹은 version 순서대로 받는다.
        await publish(room.config.room_id, room_events(room, edge_changed=True, changes=changes))
        return True


async def watch_edges(rooms: RoomRepository, *, clock: Clock, publish: Publish,
                      interval: float = CHECK_INTERVAL_SECONDS) -> None:
    """서버가 켜져 있는 동안 interval초마다 모든 방을 확인한다. lifespan에서 백그라운드 작업으로 띄운다."""
    while True:
        await asyncio.sleep(interval)
        for room in rooms.all():
            try:
                await mark_offline_if_silent(room, clock=clock, publish=publish)
            except Exception:
                # 한 방에서 예상 못 한 오류가 나도 감시 자체는 멈추지 않는다.
                logger.exception("장치 연결 확인 중 오류: %s", room.config.room_id)
