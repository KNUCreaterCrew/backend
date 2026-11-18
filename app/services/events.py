from collections.abc import Awaitable, Callable, Sequence

from app.models.rooms import RoomState, SeatChange
from app.schemas.events import EdgeStatusChanged, RoomEvent, SeatChangeItem, SeatUpdated
from app.services.rooms import summarize

Publish = Callable[[str, Sequence[RoomEvent]], Awaitable[None]]
"""방 ID와 이벤트 목록을 받아 그 방을 보고 있는 웹에 전달하는 함수."""


def room_events(room: RoomState, *, edge_changed: bool, changes: Sequence[SeatChange]) -> list[RoomEvent]:
    """방에 일어난 변경 한 번을 웹에 보낼 이벤트로 만든다.

    방 잠금 안에서, 상태를 저장한 직후에 부른다. 그래야 이벤트의 집계와 version이 방금 저장한 상태와 맞는다.
    한 번의 변경에서 나가는 이벤트는 모두 같은 version을 쓴다.
    """
    room_id = room.config.room_id
    events: list[RoomEvent] = []

    # 장치 연결이 바뀌었으면 그 사실을 먼저 알린다.
    if edge_changed:
        events.append(EdgeStatusChanged(room_id=room_id, version=room.version, edge_online=room.edge_online))

    # 좌석이 바뀌었으면 바뀐 좌석과 최신 집계를 함께 보낸다.
    if changes:
        summary = summarize(room)
        events.append(
            SeatUpdated(
                room_id=room_id,
                version=room.version,
                available_seats=summary.available_seats,
                unknown_seats=summary.unknown_seats,
                congestion_level=summary.congestion_level,
                changes=[
                    SeatChangeItem(
                        seat_id=change.seat_id,
                        prev_status=change.prev_status,
                        curr_status=change.curr_status,
                        reason=change.reason,
                        status_since=change.status_since,
                        last_observed_at=change.last_observed_at,
                    )
                    for change in changes
                ],
            )
        )
    return events
