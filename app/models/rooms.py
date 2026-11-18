import asyncio
from dataclasses import dataclass, field
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

    def transition(
        self, *, status: SeatStatus, reason: SeatReason | None, observed_at: datetime | None, at: datetime
    ) -> "SeatState":
        """이 좌석이 새 상태가 됐을 때의 SeatState를 만든다. 장치 보고와 오프라인 전환이 같은 규칙을 쓴다.

        observed_at: 새로 관측한 시각. 없으면 마지막 확인 시각을 그대로 둔다.
        at: 확인 불가가 됐을 때 상태 변경 시각으로 쓸 시각(장치 보고 시각 또는 서버 전환 시각).
        """
        last_observed_at = observed_at or self.last_observed_at

        if status == self.status:
            status_since = self.status_since  # 상태가 그대로면 시작 시각도 그대로
        elif status == SeatStatus.UNKNOWN:
            status_since = at  # 확인 불가가 된 순간
        else:
            status_since = last_observed_at or at  # 사용 중·짐 있음·빈자리를 확인한 관측 시각

        return SeatState(status=status, reason=reason, status_since=status_since, last_observed_at=last_observed_at)


@dataclass(frozen=True)
class SeatChange:
    """보고를 반영하면서 status나 reason이 달라진 좌석 하나. SEAT_UPDATED의 changes 항목이 된다."""

    seat_id: str
    prev_status: SeatStatus
    curr_status: SeatStatus
    reason: SeatReason | None
    status_since: datetime
    last_observed_at: datetime | None


@dataclass
class RoomState:
    """방 하나의 배치와 최신 상태."""

    config: RoomConfig
    edge_online: bool
    seats: dict[str, SeatState]
    version: int = 0
    """좌석·집계·장치 연결이 바뀔 때마다 1씩 커지는 번호. 웹이 이벤트 순서를 맞추는 기준이다."""
    last_report_at: datetime | None = None
    """마지막으로 인증된 보고를 받은 서버 시각. 장치 연결 판단(#13)의 기준이다."""
    lock: asyncio.Lock = field(default_factory=asyncio.Lock, repr=False, compare=False)
    """검증·비교·저장을 한 덩어리로 묶어, 같은 방의 다른 변경과 섞이지 않게 한다."""

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

    def replace_seats(self, next_states: dict[str, SeatState]) -> tuple[SeatChange, ...]:
        """좌석 상태를 한꺼번에 바꾸고, status나 reason이 달라진 좌석만 변경으로 돌려준다.

        모든 좌석 ID를 먼저 확인한 뒤 저장하므로, 없는 좌석이 섞여 있으면 아무것도 바꾸지 않는다.
        """
        unregistered = [seat_id for seat_id in next_states if seat_id not in self.seats]
        if unregistered:
            raise KeyError(f"{self.config.room_id}에 등록되지 않은 좌석입니다: {', '.join(unregistered)}")

        changes = tuple(
            SeatChange(
                seat_id=seat_id,
                prev_status=self.seats[seat_id].status,
                curr_status=state.status,
                reason=state.reason,
                status_since=state.status_since,
                last_observed_at=state.last_observed_at,
            )
            for seat_id, state in next_states.items()
            if (state.status, state.reason) != (self.seats[seat_id].status, self.seats[seat_id].reason)
        )
        self.seats.update(next_states)
        return changes
