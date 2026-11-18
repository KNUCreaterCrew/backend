"""카메라 없이 재현하는 시연 시나리오.

예시 실습실(IT4-101, 좌석 4개)에서 일어나는 일을 시간 순서대로 적는다. 시각은 시나리오 시작 후 몇 초인지로 적고,
실행할 때 실제 시각(시연) 또는 가짜 시계(테스트)에 맞춰 바꾼다.

    +0s   첫 보고           빈자리 1 / 전체 4 · 확인 불가 1
    +10s  하트비트          알림 없음
    +15s  A1에 학생이 앉음  빈자리 0
    +25s  하트비트          알림 없음
    +56s  (보고 끊김)       서버가 30초 무응답을 발견 → 전 좌석 확인 불가
    +70s  재연결            새로 확인한 좌석부터 표시
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta

ROOM_ID = "IT4-101"


@dataclass(frozen=True)
class SeatReading:
    """장치가 좌석 하나에 대해 보고하는 내용. observed는 시나리오 시작 후 몇 초에 관측했는지."""

    status: str
    observed: float | None = None
    reason: str | None = None


@dataclass(frozen=True)
class Expect:
    """한 단계를 마친 뒤 웹이 보게 될 결과."""

    events: tuple[str, ...]  # 이 단계에서 도착해야 하는 이벤트 (순서대로)
    version: int
    available: int
    unknown: int
    congestion: str
    edge_online: bool
    total: int = 4


@dataclass(frozen=True)
class Step:
    at: float  # 시나리오 시작 후 몇 초에 일어나는가
    title: str
    expect: Expect
    seats: dict[str, SeatReading] | None = field(default=None)  # None이면 장치가 보고하지 않는다.


FIRST_SEATS = {
    "A-01": SeatReading("EMPTY", observed=-2),
    "A-02": SeatReading("OCCUPIED", observed=-1),
    "B-01": SeatReading("AWAY", observed=-1),
    "B-02": SeatReading("UNKNOWN", reason="OCCLUDED"),
}
SEATED_A1 = {**FIRST_SEATS, "A-01": SeatReading("OCCUPIED", observed=14)}

INITIAL = Expect(events=(), version=0, available=0, unknown=4, congestion="HIGH", edge_online=False)
"""서버를 막 켠 방: 아직 보고를 받지 못해 전 좌석 확인 불가."""

STEPS: tuple[Step, ...] = (
    Step(0, "첫 보고: 빈자리·사용 중·짐 있음·확인 불가", seats=FIRST_SEATS, expect=Expect(
        events=("EDGE_STATUS_CHANGED", "SEAT_UPDATED"), version=1,
        available=1, unknown=1, congestion="MODERATE", edge_online=True)),
    Step(10, "하트비트 (변화 없음)", seats=FIRST_SEATS, expect=Expect(
        events=(), version=1, available=1, unknown=1, congestion="MODERATE", edge_online=True)),
    Step(15, "학생이 A1에 앉음", seats=SEATED_A1, expect=Expect(
        events=("SEAT_UPDATED",), version=2, available=0, unknown=1, congestion="HIGH", edge_online=True)),
    Step(25, "하트비트 (A1을 다시 확인, 상태는 그대로)",
         seats={**SEATED_A1, "A-01": SeatReading("OCCUPIED", observed=24)}, expect=Expect(
        events=(), version=2, available=0, unknown=1, congestion="HIGH", edge_online=True)),
    Step(56, "장치 응답 없음 (마지막 보고 후 31초)", seats=None, expect=Expect(
        events=("EDGE_STATUS_CHANGED", "SEAT_UPDATED"), version=3,
        available=0, unknown=4, congestion="HIGH", edge_online=False)),
    Step(70, "장치 재연결: 새로 확인한 좌석부터 표시", seats={
        "A-01": SeatReading("OCCUPIED", observed=69),
        "A-02": SeatReading("EMPTY", observed=68),
        "B-01": SeatReading("UNKNOWN", reason="STALE_OBSERVATION"),  # 끊긴 동안 30초 넘게 못 봄
        "B-02": SeatReading("UNKNOWN", reason="OCCLUDED"),
    }, expect=Expect(
        events=("EDGE_STATUS_CHANGED", "SEAT_UPDATED"), version=4,
        available=1, unknown=2, congestion="MODERATE", edge_online=True)),
)


def build_report(step: Step, start: datetime) -> dict:
    """단계의 좌석 내용을 공통 명세 형식의 장치 보고 JSON으로 만든다. 영상·이미지는 담지 않는다."""
    assert step.seats is not None

    def at(seconds: float) -> str:
        return (start + timedelta(seconds=seconds)).isoformat()

    return {
        "room_id": ROOM_ID,
        "timestamp": at(step.at),
        "inference_fps": 2.0,
        "saved_frames_count": 0,
        "seats": [
            {
                "seat_id": seat_id,
                "status": reading.status,
                "confidence": None,
                "reason": reading.reason,
                "last_observed_at": at(reading.observed) if reading.observed is not None else None,
            }
            for seat_id, reading in step.seats.items()
        ],
    }
