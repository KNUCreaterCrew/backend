from enum import StrEnum
from typing import Literal

from pydantic import AwareDatetime, BaseModel


class SeatStatus(StrEnum):
    EMPTY = "EMPTY"
    OCCUPIED = "OCCUPIED"
    AWAY = "AWAY"
    UNKNOWN = "UNKNOWN"


class SeatLayout(BaseModel):
    x: int
    y: int
    width: int
    height: int


class Seat(BaseModel):
    seat_id: str
    label: str
    status: SeatStatus
    status_since: AwareDatetime
    last_observed_at: AwareDatetime | None
    has_outlet: bool
    is_window: bool
    layout: SeatLayout


class Room(BaseModel):
    room_id: str
    room_name: str
    edge_online: bool
    seats: tuple[Seat, ...]


CongestionLevel = Literal["LOW", "MODERATE", "HIGH"]


class RoomSnapshot(Room):
    total_seats: int
    available_seats: int
    unknown_seats: int
    congestion_level: CongestionLevel
