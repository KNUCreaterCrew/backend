from dataclasses import dataclass
from datetime import datetime

from app.models.rooms import SeatChange
from app.repositories.rooms import RoomRepository
from app.schemas.reports import StatusReport
from app.services.events import Publish, room_events


class RoomNotFound(Exception):
    pass


class InvalidReport(Exception):
    """형식은 맞지만 이 방에 반영할 수 없는 보고. 방 상태는 바뀌지 않는다."""


@dataclass(frozen=True)
class ReportOutcome:
    """보고 하나를 반영한 결과. 응답의 updated_count와 테스트가 쓴다."""

    room_id: str
    version: int
    edge_came_online: bool
    changes: tuple[SeatChange, ...]


async def apply_status_report(
    rooms: RoomRepository, room_id: str, report: StatusReport, *, received_at: datetime, publish: Publish
) -> ReportOutcome:
    """인증된 보고를 방 상태에 반영하고, 바뀐 것이 있으면 그 방을 보고 있는 웹에 알린다.

    검증에 실패하면 어떤 좌석도 바꾸지 않고 아무것도 보내지 않는다.
    """
    room = rooms.find(room_id)
    if room is None:
        raise RoomNotFound(room_id)

    async with room.lock:
        # 1. 검증: 하나라도 틀리면 아무것도 저장하지 않고 끝낸다.
        if report.room_id != room_id:
            raise InvalidReport(f"경로의 방 ID({room_id})와 보고의 방 ID({report.room_id})가 다릅니다.")
        unregistered = [seat.seat_id for seat in report.seats if seat.seat_id not in room.seats]
        if unregistered:
            raise InvalidReport(f"{room_id}에 등록되지 않은 좌석입니다: {', '.join(unregistered)}")

        # 2. 비교: 보고에 담긴 좌석마다 새 상태를 계산한다. (보고에 없는 좌석은 그대로 둔다.)
        next_states = {
            seat.seat_id: room.seats[seat.seat_id].transition(
                status=seat.status, reason=seat.reason, observed_at=seat.last_observed_at, at=report.timestamp
            )
            for seat in report.seats
        }
        edge_came_online = not room.edge_online

        # 3. 저장: status나 reason이 달라진 좌석이 변경(changes)이 된다.
        changes = room.replace_seats(next_states)
        room.edge_online = True
        room.last_report_at = received_at
        if changes or edge_came_online:
            room.version += 1

        # 4. 알림: 잠금을 쥔 채로 보낸다. 다음 변경은 이 전송이 끝난 뒤에 시작하므로
        #    웹은 version 1, 2, 3을 항상 이 순서로 받는다. 바뀐 것이 없으면 보낼 이벤트도 없다.
        await publish(room_id, room_events(room, edge_changed=edge_came_online, changes=changes))

        return ReportOutcome(
            room_id=room_id, version=room.version, edge_came_online=edge_came_online, changes=changes
        )
