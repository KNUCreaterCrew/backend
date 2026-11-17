from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Self

from pydantic import AwareDatetime, BaseModel, ConfigDict, model_validator


class SeatStatus(StrEnum):
    EMPTY = "EMPTY"
    OCCUPIED = "OCCUPIED"
    AWAY = "AWAY"
    UNKNOWN = "UNKNOWN"


class SeatReason(StrEnum):
    """좌석이 UNKNOWN인 이유."""

    OCCLUDED = "OCCLUDED"
    LOW_CONFIDENCE = "LOW_CONFIDENCE"
    MODEL_CONFLICT = "MODEL_CONFLICT"
    VLM_TIMEOUT = "VLM_TIMEOUT"
    STALE_OBSERVATION = "STALE_OBSERVATION"
    EDGE_OFFLINE = "EDGE_OFFLINE"


# 배치: 설정 파일에서 읽고, 서버가 도는 동안 바뀌지 않는다.


class SeatLayout(BaseModel):
    model_config = ConfigDict(frozen=True)

    x: int
    y: int
    width: int
    height: int


class SeatConfig(BaseModel):
    model_config = ConfigDict(frozen=True)

    seat_id: str
    label: str
    has_outlet: bool
    is_window: bool
    layout: SeatLayout


class RoomConfig(BaseModel):
    model_config = ConfigDict(frozen=True)

    room_id: str
    room_name: str
    seats: tuple[SeatConfig, ...]

    @model_validator(mode="after")
    def _seat_ids_are_unique(self) -> Self:
        seat_ids = [seat.seat_id for seat in self.seats]
        if len(seat_ids) != len(set(seat_ids)):
            raise ValueError(f"{self.room_id}: 좌석 ID가 중복됐습니다.")
        return self


# 상태: 메모리에만 두고, 장치 보고와 연결 감시에 따라 바뀐다.


class SeatState(BaseModel):
    model_config = ConfigDict(frozen=True)

    status: SeatStatus
    reason: SeatReason | None = None
    status_since: AwareDatetime
    last_observed_at: AwareDatetime | None = None

    @model_validator(mode="after")
    def _reason_only_when_unknown(self) -> Self:
        if self.reason is not None and self.status != SeatStatus.UNKNOWN:
            raise ValueError("reason은 UNKNOWN 좌석에만 둔다.")
        return self

    @classmethod
    def unobserved(cls, since: datetime) -> Self:
        """아직 보고를 받지 못한 좌석. 장치 통신 두절과 같은 사유로 본다."""
        return cls(status=SeatStatus.UNKNOWN, reason=SeatReason.EDGE_OFFLINE, status_since=since)


@dataclass
class RoomState:
    """방 하나의 배치와 최신 상태."""

    config: RoomConfig
    edge_online: bool
    seats: dict[str, SeatState]

    @classmethod
    def unobserved(cls, config: RoomConfig, since: datetime) -> Self:
        return cls(
            config=config,
            edge_online=False,
            seats={seat.seat_id: SeatState.unobserved(since) for seat in config.seats},
        )

    def set_seat(self, seat_id: str, state: SeatState) -> None:
        if seat_id not in self.seats:
            raise KeyError(f"{self.config.room_id}에 등록되지 않은 좌석입니다: {seat_id}")
        self.seats[seat_id] = state
