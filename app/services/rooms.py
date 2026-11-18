from dataclasses import dataclass

from app.models.rooms import RoomState, SeatConfig, SeatState, SeatStatus
from app.repositories.rooms import RoomRepository
from app.schemas.rooms import (
    CongestionLevel,
    RoomSnapshot,
    RoomSummaryResponse,
    SeatLayoutResponse,
    SeatResponse,
)


def congestion_level(available_seats: float, total_seats: int) -> CongestionLevel:
    """빈자리 비율로 혼잡도를 정한다. 통계에서는 반올림한 평균 빈자리(소수)를 넣는다."""
    available_ratio = available_seats / total_seats if total_seats else 0
    if available_ratio >= 0.60:
        return "LOW"
    if available_ratio >= 0.25:
        return "MODERATE"
    return "HIGH"


@dataclass(frozen=True)
class RoomSummary:
    total_seats: int
    available_seats: int
    unknown_seats: int
    congestion_level: CongestionLevel


def summarize(room: RoomState) -> RoomSummary:
    """방의 현재 좌석 상태로 집계를 낸다. 조회 응답과 실시간 알림이 모두 이 함수를 쓴다."""
    statuses = [room.seats[seat.seat_id].status for seat in room.config.seats]
    total = len(statuses)
    available = statuses.count(SeatStatus.EMPTY)
    unknown = statuses.count(SeatStatus.UNKNOWN)
    return RoomSummary(total, available, unknown, congestion_level(available, total))


def _seat_response(config: SeatConfig, state: SeatState) -> SeatResponse:
    """설정의 배치와 메모리의 상태를 합쳐 좌석 하나의 응답을 만든다."""
    return SeatResponse(
        seat_id=config.seat_id,
        label=config.label,
        status=state.status,
        reason=state.reason,
        status_since=state.status_since,
        last_observed_at=state.last_observed_at,
        has_outlet=config.has_outlet,
        is_window=config.is_window,
        layout=SeatLayoutResponse(**config.layout.model_dump()),
    )


def _summary_fields(room: RoomState) -> dict:
    """목록 항목과 방 조회 응답이 함께 쓰는 필드. 숫자는 summarize()로만 계산한다."""
    summary = summarize(room)
    return {
        "room_id": room.config.room_id,
        "room_name": room.config.room_name,
        "total_seats": summary.total_seats,
        "available_seats": summary.available_seats,
        "unknown_seats": summary.unknown_seats,
        "congestion_level": summary.congestion_level,
        "edge_online": room.edge_online,
    }


def list_room_summaries(rooms: RoomRepository) -> list[RoomSummaryResponse]:
    """등록된 방마다 요약을 낸다. 순서는 배치 설정 파일에 적힌 순서다."""
    return [RoomSummaryResponse(**_summary_fields(room)) for room in rooms.all()]


def get_room_snapshot(rooms: RoomRepository, room_id: str) -> RoomSnapshot | None:
    room = rooms.find(room_id)
    if room is None:
        return None

    seats = [_seat_response(seat, room.seats[seat.seat_id]) for seat in room.config.seats]
    return RoomSnapshot(**_summary_fields(room), version=room.version, seats=seats)
