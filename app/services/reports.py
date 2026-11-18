from dataclasses import dataclass
from datetime import datetime

from app.models.rooms import SeatChange, SeatState, SeatStatus
from app.repositories.rooms import RoomRepository
from app.schemas.reports import SeatReport, StatusReport
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


def next_seat_state(current: SeatState, seat: SeatReport, reported_at: datetime) -> SeatState:
    """저장된 좌석 상태에 보고 한 줄을 적용한 새 상태를 만든다. 저장은 하지 않는다."""
    # 새 관측이 없으면 마지막 확인 시각을 그대로 둔다.
    last_observed_at = seat.last_observed_at or current.last_observed_at

    if seat.status == current.status:
        status_since = current.status_since
    elif seat.status == SeatStatus.UNKNOWN:
        # 확인 불가가 된 순간은 관측 시각이 아니라 장치가 보고를 만든 시각이다.
        status_since = reported_at
    else:
        # 사용 중·짐 있음·빈자리는 그 상태를 확인한 관측 시각부터다.
        status_since = last_observed_at or reported_at

    return SeatState(
        status=seat.status,
        reason=seat.reason,
        status_since=status_since,
        last_observed_at=last_observed_at,
    )


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

        # 2. 비교: 새 상태를 모두 계산한 뒤, status나 reason이 달라진 좌석만 변경으로 센다.
        next_states = {
            seat.seat_id: next_seat_state(room.seats[seat.seat_id], seat, report.timestamp)
            for seat in report.seats
        }
        changes = tuple(
            SeatChange(
                seat_id=seat_id,
                prev_status=room.seats[seat_id].status,
                curr_status=state.status,
                reason=state.reason,
                status_since=state.status_since,
                last_observed_at=state.last_observed_at,
            )
            for seat_id, state in next_states.items()
            if (state.status, state.reason) != (room.seats[seat_id].status, room.seats[seat_id].reason)
        )
        edge_came_online = not room.edge_online

        # 3. 저장: 보고에 없는 좌석은 그대로 둔다.
        for seat_id, state in next_states.items():
            room.set_seat(seat_id, state)
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
