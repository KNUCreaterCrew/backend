from typing import Literal

from pydantic import AwareDatetime, BaseModel

from app.models.rooms import SeatReason, SeatStatus

CongestionLevel = Literal["LOW", "MODERATE", "HIGH"]


class SeatLayoutResponse(BaseModel):
    x: int
    y: int
    width: int
    height: int


class SeatResponse(BaseModel):
    seat_id: str
    label: str
    status: SeatStatus
    reason: SeatReason | None
    status_since: AwareDatetime
    last_observed_at: AwareDatetime | None
    has_outlet: bool
    is_window: bool
    layout: SeatLayoutResponse


class RoomSnapshot(BaseModel):
    room_id: str
    room_name: str
    total_seats: int
    available_seats: int
    unknown_seats: int
    congestion_level: CongestionLevel
    edge_online: bool
    version: int
    seats: list[SeatResponse]
