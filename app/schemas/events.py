"""WebSocket으로 웹에 보내는 이벤트의 형식. 공통 명세 INTERFACES.md 3번과 같은 모양이다."""

from typing import Literal

from pydantic import AwareDatetime, BaseModel

from app.models.rooms import SeatReason, SeatStatus
from app.schemas.rooms import CongestionLevel


class EdgeStatusChanged(BaseModel):
    """장치 연결 여부가 바뀌었다."""

    event: Literal["EDGE_STATUS_CHANGED"] = "EDGE_STATUS_CHANGED"
    room_id: str
    version: int
    edge_online: bool


class SeatChangeItem(BaseModel):
    """바뀐 좌석 하나. 웹은 이 좌석의 표시만 고치면 된다."""

    seat_id: str
    prev_status: SeatStatus
    curr_status: SeatStatus
    reason: SeatReason | None
    status_since: AwareDatetime
    last_observed_at: AwareDatetime | None
    """상태가 바뀐 순간의 마지막 확인 시각. 상태가 그대로인 동안의 갱신은 웹이 30초마다 다시 조회해 맞춘다."""


class SeatUpdated(BaseModel):
    """좌석이 바뀌었다. 바뀐 좌석과 함께 방의 최신 집계를 싣는다."""

    event: Literal["SEAT_UPDATED"] = "SEAT_UPDATED"
    room_id: str
    version: int
    available_seats: int
    unknown_seats: int
    congestion_level: CongestionLevel
    changes: list[SeatChangeItem]


RoomEvent = EdgeStatusChanged | SeatUpdated
