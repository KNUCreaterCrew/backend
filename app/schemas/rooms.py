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


class RoomSummaryResponse(BaseModel):
    """방 목록의 한 항목. 방 조회 응답도 이 필드로 시작하므로 이름과 뜻이 같다."""

    room_id: str
    room_name: str
    total_seats: int
    available_seats: int
    unknown_seats: int
    congestion_level: CongestionLevel
    edge_online: bool


class RoomSnapshot(RoomSummaryResponse):
    """방 하나의 조회 응답. 목록 항목에 이벤트 순서 번호와 좌석 목록을 더한다."""

    version: int
    seats: list[SeatResponse]
