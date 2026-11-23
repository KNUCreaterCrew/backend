"""장치 연결 끊김과 복구를 확인한다.

앞부분은 시계를 직접 옮기며 mark_offline_if_silent()의 30초 경계와 전환 규칙을 확인하고,
뒷부분은 백그라운드 감시 작업을 실제로 돌려 공통 명세의 흐름(첫 보고 → 하트비트 → 끊김 → 재연결)을 재현한다.
"""

import asyncio
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.models.rooms import RoomConfig, SeatReason, SeatStatus
from app.repositories.rooms import ROOMS_CONFIG_PATH, RoomRepository
from app.schemas.reports import StatusReport
from app.services.edge import mark_offline_if_silent, watch_edges
from app.services.reports import apply_status_report
from app.services.rooms import get_room_snapshot
from tests.conftest import KST, TEST_EDGE_API_KEY, FakeClock, settings_with_test_key

T0 = datetime(2026, 11, 24, 10, 15, 40, tzinfo=KST)  # 마지막 보고를 받은 서버 시각


def kst(hhmmss: str) -> str:
    return f"2026-11-24T{hhmmss}+09:00"


def report(timestamp: str, *seats: dict, room_id: str = "IT4-108") -> StatusReport:
    return StatusReport.model_validate({
        "room_id": room_id, "timestamp": kst(timestamp), "inference_fps": 2.0, "saved_frames_count": 0,
        "seats": list(seats),
    })


def seat(seat_id: str, status: str, observed: str | None = None, reason: str | None = None) -> dict:
    return {"seat_id": seat_id, "status": status, "confidence": None, "reason": reason,
            "last_observed_at": kst(observed) if observed else None}


class Recorder:
    """publish 자리에 꽂아, 보내려던 이벤트를 기록만 한다."""

    def __init__(self) -> None:
        self.sent: list[list[dict]] = []

    async def __call__(self, room_id, events) -> None:
        self.sent.append([event.model_dump(mode="json") for event in events])


SIX_SEATS = report(
    "10:15:40",
    seat("A-01", "EMPTY", "10:15:38"),
    seat("A-02", "OCCUPIED", "10:15:39"),
    seat("A-03", "EMPTY", "10:15:38"),
    seat("B-01", "AWAY", "10:15:39"),
    seat("B-02", "UNKNOWN", reason="OCCLUDED"),
    seat("B-03", "OCCUPIED", "10:15:39"),
)


@pytest.fixture
def online_rooms() -> RoomRepository:
    """여섯 좌석 방(IT4-108)이 10:15:40에 보고를 받은 상태."""
    rooms = RoomRepository.from_config_file(ROOMS_CONFIG_PATH, started_at=T0 - timedelta(minutes=10))
    asyncio.run(apply_status_report(rooms, "IT4-108", SIX_SEATS, received_at=T0, publish=Recorder()))
    return rooms


def check(rooms: RoomRepository, at: datetime, publish=None) -> bool:
    publish = publish or Recorder()
    return asyncio.run(mark_offline_if_silent(rooms.find("IT4-108"), clock=lambda: at, publish=publish))


# ── 30초 경계 ────────────────────────────────────────────────────


def test_room_stays_online_just_before_30_seconds(online_rooms):
    recorder = Recorder()

    changed = check(online_rooms, T0 + timedelta(seconds=30) - timedelta(microseconds=1), recorder)

    assert changed is False
    assert recorder.sent == []
    assert online_rooms.find("IT4-108").edge_online is True


def test_room_goes_offline_at_30_seconds(online_rooms):
    recorder = Recorder()

    changed = check(online_rooms, T0 + timedelta(seconds=30), recorder)

    room = online_rooms.find("IT4-108")
    assert changed is True
    assert room.edge_online is False
    assert room.version == 2
    assert [event["event"] for event in recorder.sent[0]] == ["EDGE_STATUS_CHANGED", "SEAT_UPDATED"]


def test_offline_transition_is_not_repeated(online_rooms):
    check(online_rooms, T0 + timedelta(seconds=30))
    recorder = Recorder()

    changed = check(online_rooms, T0 + timedelta(minutes=5), recorder)

    assert changed is False
    assert recorder.sent == []
    assert online_rooms.find("IT4-108").version == 2


def test_room_that_never_reported_is_left_alone():
    rooms = RoomRepository.from_config_file(ROOMS_CONFIG_PATH, started_at=T0)

    assert check(rooms, T0 + timedelta(hours=1)) is False
    assert rooms.find("IT4-108").version == 0


# ── 오프라인 전환 규칙 ───────────────────────────────────────────


def test_every_seat_becomes_unknown_but_keeps_its_last_observed_time(online_rooms):
    offline_at = T0 + timedelta(seconds=31)
    recorder = Recorder()

    check(online_rooms, offline_at, recorder)

    seats = online_rooms.find("IT4-108").seats
    for seat_id in ("A-01", "A-02", "A-03", "B-01", "B-02", "B-03"):
        assert (seats[seat_id].status, seats[seat_id].reason) == (SeatStatus.UNKNOWN, SeatReason.EDGE_OFFLINE)
    # 상태가 바뀐 좌석의 상태 변경 시각은 서버가 전환한 시각, 마지막 확인 시각은 그대로다.
    assert seats["A-01"].status_since == offline_at
    assert seats["A-01"].last_observed_at == datetime.fromisoformat(kst("10:15:38"))
    # B-02는 서버 시작(10:05:40)부터 계속 확인 불가였다. 사유만 OCCLUDED → EDGE_OFFLINE으로 바뀌고
    # 상태 변경 시각은 유지된다. 보고 반영과 같은 규칙(상태가 바뀐 좌석만 status_since를 새로 정함)이다.
    assert seats["B-02"].status_since == T0 - timedelta(minutes=10)

    seat_updated = recorder.sent[0][1]
    assert len(seat_updated["changes"]) == 6  # 사유만 바뀐 B-02도 변경이다.
    assert (seat_updated["available_seats"], seat_updated["unknown_seats"]) == (0, 6)


def test_event_and_room_snapshot_agree_after_going_offline(online_rooms):
    recorder = Recorder()

    check(online_rooms, T0 + timedelta(seconds=31), recorder)

    edge, seat_updated = recorder.sent[0]
    snapshot = get_room_snapshot(online_rooms, "IT4-108")
    assert edge["edge_online"] is snapshot.edge_online is False
    assert seat_updated["version"] == edge["version"] == snapshot.version
    assert seat_updated["available_seats"] == snapshot.available_seats
    assert seat_updated["unknown_seats"] == snapshot.unknown_seats
    assert seat_updated["congestion_level"] == snapshot.congestion_level


def test_reconnect_shows_only_what_the_new_report_confirms(online_rooms):
    """재연결만으로 끊기기 전의 빈자리를 되살리지 않는다."""
    check(online_rooms, T0 + timedelta(seconds=31))
    # 장치는 끊긴 동안 A1을 30초 넘게 보지 못했다. 그래서 A1을 관측 만료로 보낸다.
    reconnect = report("10:17:05", seat("A-01", "UNKNOWN", reason="STALE_OBSERVATION"), seat("A-02", "OCCUPIED", "10:17:04"))

    asyncio.run(apply_status_report(online_rooms, "IT4-108", reconnect, received_at=T0 + timedelta(seconds=85),
                                    publish=Recorder()))

    room = online_rooms.find("IT4-108")
    snapshot = get_room_snapshot(online_rooms, "IT4-108")
    assert room.edge_online is True
    assert room.seats["A-01"].status == SeatStatus.UNKNOWN  # 끊기기 전 EMPTY가 되살아나지 않는다.
    assert room.seats["A-02"].status == SeatStatus.OCCUPIED
    assert room.seats["B-01"].reason == SeatReason.EDGE_OFFLINE  # 보고에 없는 좌석은 그대로
    assert snapshot.available_seats == 0


def test_offline_check_and_report_at_the_same_time_stay_in_order(online_rooms):
    """감시 작업과 장치 보고가 동시에 들어와도 한 번에 하나씩 처리되고, 알림은 version 순서대로 나간다."""
    delivered: list[tuple[int, bool]] = []

    async def slow_publish(room_id, events) -> None:
        await asyncio.sleep(0.02)
        delivered.append((events[0].version, events[0].edge_online))

    async def both() -> None:
        now = T0 + timedelta(seconds=31)
        room = online_rooms.find("IT4-108")
        await asyncio.gather(
            mark_offline_if_silent(room, clock=lambda: now, publish=slow_publish),
            apply_status_report(online_rooms, "IT4-108", report("10:16:11", seat("A-01", "OCCUPIED", "10:16:10")),
                                received_at=now, publish=slow_publish),
        )

    asyncio.run(both())

    room = online_rooms.find("IT4-108")
    assert delivered == [(2, False), (3, True)]  # 끊김 → 재연결 순서
    assert room.edge_online is True  # 마지막으로 들어온 보고가 최종 상태
    assert room.seats["A-01"].status == SeatStatus.OCCUPIED


# ── 감시 작업 ────────────────────────────────────────────────────


def test_watcher_keeps_going_when_one_room_fails(caplog):
    seat_config = {"seat_id": "A-01", "label": "A1", "has_outlet": True, "is_window": True,
                   "layout": {"x": 0, "y": 0, "width": 64, "height": 48}}
    rooms = RoomRepository([RoomConfig(room_id=room_id, room_name=room_id, seats=[seat_config])
                            for room_id in ("ROOM-1", "ROOM-2")], started_at=T0)
    for room_id in ("ROOM-1", "ROOM-2"):
        body = report("10:15:40", seat("A-01", "OCCUPIED", "10:15:39"), room_id=room_id)
        asyncio.run(apply_status_report(rooms, room_id, body, received_at=T0, publish=Recorder()))

    async def broken_for_room_1(room_id, events) -> None:
        if room_id == "ROOM-1":
            raise RuntimeError("전송 실패")

    async def run_watcher_briefly() -> None:
        with pytest.raises(TimeoutError):
            async with asyncio.timeout(0.1):
                await watch_edges(rooms, clock=lambda: T0 + timedelta(seconds=31), publish=broken_for_room_1,
                                  interval=0.01)

    asyncio.run(run_watcher_briefly())

    assert rooms.find("ROOM-2").edge_online is False  # ROOM-1의 오류와 상관없이 처리됐다.
    assert "ROOM-1" in caplog.text


# ── 공통 명세의 흐름 전체 ────────────────────────────────────────


@pytest.fixture
def spec_app():
    """명세 예시와 같은 한 좌석 방. 감시 작업을 0.01초마다 돌리고, 서버 시계는 테스트가 옮긴다."""
    seat_config = {"seat_id": "A-01", "label": "A1", "has_outlet": True, "is_window": True,
                   "layout": {"x": 120, "y": 80, "width": 64, "height": 48}}
    rooms = RoomRepository([RoomConfig(room_id="IT4-101", room_name="제1실습실", seats=[seat_config])],
                           started_at=datetime(2026, 11, 24, 10, 0, tzinfo=KST))
    clock = FakeClock(datetime(2026, 11, 24, 10, 0, tzinfo=KST))
    app = create_app(lambda: rooms, settings_with_test_key, clock, edge_check_interval=0.01)
    with TestClient(app) as client:
        yield client, clock


def post(client: TestClient, body: StatusReport):
    return client.post("/api/v1/rooms/IT4-101/seats/status", content=body.model_dump_json(),
                       headers={"X-Edge-Api-Key": TEST_EDGE_API_KEY, "Content-Type": "application/json"})


def at(hhmmss: str, micro: int = 0) -> datetime:
    return datetime.fromisoformat(kst(hhmmss)).replace(microsecond=micro)


def test_spec_flow_first_report_heartbeat_offline_and_reconnect(spec_app):
    client, clock = spec_app
    with client.websocket_connect("/ws/rooms/IT4-101") as ws:
        # 10:15:30 첫 보고 → version 1
        clock.now = at("10:15:30", 112000)
        post(client, report("10:15:30", seat("A-01", "OCCUPIED", "10:15:29"), room_id="IT4-101"))
        assert [ws.receive_json()["version"], ws.receive_json()["version"]] == [1, 1]

        # 10:15:40 새 관측 없는 하트비트 → 알림 없음, 서버 수신 시각만 기록
        clock.now = at("10:15:40", 105000)
        post(client, report("10:15:40", seat("A-01", "OCCUPIED", "10:15:29"), room_id="IT4-101"))

        # 10:16:11 감시 작업이 30초 넘은 것을 발견 → version 2 (명세 예시와 같은 JSON)
        clock.now = at("10:16:11")
        assert ws.receive_json() == {
            "event": "EDGE_STATUS_CHANGED", "room_id": "IT4-101", "version": 2, "edge_online": False,
        }
        assert ws.receive_json() == {
            "event": "SEAT_UPDATED", "room_id": "IT4-101", "version": 2,
            "available_seats": 0, "unknown_seats": 1, "congestion_level": "HIGH",
            "changes": [{"seat_id": "A-01", "prev_status": "OCCUPIED", "curr_status": "UNKNOWN",
                         "reason": "EDGE_OFFLINE", "status_since": "2026-11-24T10:16:11+09:00",
                         "last_observed_at": "2026-11-24T10:15:29+09:00"}],
        }
        offline = client.get("/api/v1/rooms/IT4-101").json()

        # 10:17:05 장치가 다시 보고 → version 3
        clock.now = at("10:17:05", 87000)
        ack = post(client, report("10:17:05", seat("A-01", "OCCUPIED", "10:17:04"), room_id="IT4-101")).json()
        assert ws.receive_json() == {
            "event": "EDGE_STATUS_CHANGED", "room_id": "IT4-101", "version": 3, "edge_online": True,
        }
        reconnected = ws.receive_json()

    assert (offline["edge_online"], offline["unknown_seats"], offline["version"]) == (False, 1, 2)
    assert offline["seats"][0]["last_observed_at"] == "2026-11-24T10:15:29+09:00"
    assert ack["updated_count"] == 1
    assert reconnected["version"] == 3
    assert reconnected["changes"] == [
        {"seat_id": "A-01", "prev_status": "UNKNOWN", "curr_status": "OCCUPIED", "reason": None,
         "status_since": "2026-11-24T10:17:04+09:00", "last_observed_at": "2026-11-24T10:17:04+09:00"}
    ]
