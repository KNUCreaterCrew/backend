from typing import Literal, Self

from pydantic import AwareDatetime, BaseModel, Field, model_validator

from app.models.rooms import SeatReason, SeatStatus

DecisionSource = Literal["YOLO", "YOLO_VLM", "FALLBACK"]


class SeatReport(BaseModel):
    """장치가 판정한 좌석 하나의 상태."""

    seat_id: str
    status: SeatStatus
    reason: SeatReason | None = None
    confidence: float | None = Field(default=None, ge=0, le=1)
    decision_source: DecisionSource | None = None
    last_observed_at: AwareDatetime | None = None

    @model_validator(mode="after")
    def _reason_only_when_unknown(self) -> Self:
        if self.reason is not None and self.status != SeatStatus.UNKNOWN:
            raise ValueError("reason은 UNKNOWN 좌석에만 보낼 수 있습니다.")
        return self


class StatusReport(BaseModel):
    """장치가 맡은 좌석 전체를 담아 보내는 상태 보고. 하트비트도 같은 형식이다."""

    room_id: str
    timestamp: AwareDatetime
    inference_fps: float = Field(ge=0)
    saved_frames_count: int = Field(ge=0)
    seats: list[SeatReport] = Field(min_length=1)

    @model_validator(mode="after")
    def _seat_ids_are_unique(self) -> Self:
        seat_ids = [seat.seat_id for seat in self.seats]
        if len(seat_ids) != len(set(seat_ids)):
            raise ValueError("한 보고에 같은 좌석 ID가 두 번 들어 있습니다.")
        return self


class StatusReportAck(BaseModel):
    ok: Literal[True] = True
    updated_count: int
    """status나 reason이 실제로 바뀐 좌석 수. 같은 보고를 다시 보내면 0이다."""
    server_time: AwareDatetime
    """서버가 보고를 받은 시각."""
