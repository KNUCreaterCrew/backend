from app.models.rooms import SeatConfig, SeatState, SeatStatus
from app.repositories.rooms import RoomRepository
from app.schemas.rooms import CongestionLevel, RoomSnapshot, SeatLayoutResponse, SeatResponse


def congestion_level(available_seats: int, total_seats: int) -> CongestionLevel:
    available_ratio = available_seats / total_seats if total_seats else 0
    if available_ratio >= 0.60:
        return "LOW"
    if available_ratio >= 0.25:
        return "MODERATE"
    return "HIGH"


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


def get_room_snapshot(rooms: RoomRepository, room_id: str) -> RoomSnapshot | None:
    room = rooms.find(room_id)
    if room is None:
        return None

    seats = [_seat_response(seat, room.seats[seat.seat_id]) for seat in room.config.seats]
    total = len(seats)
    available = sum(seat.status == SeatStatus.EMPTY for seat in seats)
    unknown = sum(seat.status == SeatStatus.UNKNOWN for seat in seats)
    return RoomSnapshot(
        room_id=room.config.room_id,
        room_name=room.config.room_name,
        total_seats=total,
        available_seats=available,
        unknown_seats=unknown,
        congestion_level=congestion_level(available, total),
        edge_online=room.edge_online,
        seats=seats,
    )
