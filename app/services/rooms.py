from app.models.rooms import SeatStatus
from app.repositories.rooms import RoomRepository
from app.schemas.rooms import CongestionLevel, RoomSnapshot, SeatResponse


def congestion_level(available_seats: int, total_seats: int) -> CongestionLevel:
    available_ratio = available_seats / total_seats if total_seats else 0
    if available_ratio >= 0.60:
        return "LOW"
    if available_ratio >= 0.25:
        return "MODERATE"
    return "HIGH"


def get_room_snapshot(rooms: RoomRepository, room_id: str) -> RoomSnapshot | None:
    room = rooms.find(room_id)
    if room is None:
        return None

    total = len(room.seats)
    available = sum(seat.status == SeatStatus.EMPTY for seat in room.seats)
    unknown = sum(seat.status == SeatStatus.UNKNOWN for seat in room.seats)
    return RoomSnapshot(
        room_id=room.room_id,
        room_name=room.room_name,
        total_seats=total,
        available_seats=available,
        unknown_seats=unknown,
        congestion_level=congestion_level(available, total),
        edge_online=room.edge_online,
        seats=[SeatResponse.model_validate(seat) for seat in room.seats],
    )
