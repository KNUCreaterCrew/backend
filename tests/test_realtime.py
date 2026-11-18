"""WebSocket 변경 알림을 확인한다.

TestClient의 websocket_connect()는 실제 브라우저 대신 연결 하나를 열어 준다.
    ws.receive_json()  서버가 보낸 다음 메시지를 기다려 받는다. (안 오면 계속 기다린다.)
그래서 "아무것도 오지 않았다"는 직접 확인할 수 없다. 대신 뒤이어 확실히 알림이 가는 변경을 만들고,
처음 받은 메시지가 그 변경인지 본다. 그 앞에 다른 메시지가 끼어 있었다면 테스트가 실패한다.
"""

import asyncio
import copy
from datetime import datetime

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.connections import SLOW_CLIENT_CLOSE_CODE, RoomConnections
from app.main import create_app
from app.models.rooms import RoomConfig
from app.repositories.rooms import RoomRepository
from app.schemas.events import EdgeStatusChanged
from app.schemas.reports import StatusReport
from app.services.reports import apply_status_report
from tests.conftest import KST, TEST_EDGE_API_KEY, FakeClock, settings_with_test_key


def seat_config(seat_id: str, label: str) -> dict:
    return {"seat_id": seat_id, "label": label, "has_outlet": True, "is_window": True,
            "layout": {"x": 120, "y": 80, "width": 64, "height": 48}}


@pytest.fixture
def client() -> TestClient:
    """명세 예시와 같은 한 좌석 방(IT4-101)과, 좌석 두 개인 다른 방(IT4-102)."""
    rooms = RoomRepository(
        [
            RoomConfig(room_id="IT4-101", room_name="제1실습실", seats=[seat_config("A-01", "A1")]),
            RoomConfig(room_id="IT4-102", room_name="제2실습실",
                       seats=[seat_config("A-01", "A1"), seat_config("A-02", "A2")]),
        ],
        started_at=datetime(2026, 11, 24, 10, 0, tzinfo=KST),
    )
    clock = FakeClock(datetime(2026, 11, 24, 10, 0, tzinfo=KST))
    with TestClient(create_app(lambda: rooms, settings_with_test_key, clock)) as client:
        yield client


def report(room_id: str, timestamp: str, *seats: tuple[str, str, str]) -> dict:
    """seats는 (좌석 ID, 상태, 마지막 관측 시각) 묶음."""
    return {
        "room_id": room_id,
        "timestamp": f"2026-11-24T{timestamp}+09:00",
        "inference_fps": 2.1,
        "saved_frames_count": 0,
        "seats": [
            {"seat_id": seat_id, "status": status, "confidence": None,
             "last_observed_at": f"2026-11-24T{observed}+09:00"}
            for seat_id, status, observed in seats
        ],
    }


def post(client: TestClient, body: dict, key: str = TEST_EDGE_API_KEY):
    return client.post(f"/api/v1/rooms/{body['room_id']}/seats/status", json=body,
                       headers={"X-Edge-Api-Key": key})


FIRST_REPORT = report("IT4-101", "10:15:30", ("A-01", "OCCUPIED", "10:15:29"))
HEARTBEAT = report("IT4-101", "10:15:40", ("A-01", "OCCUPIED", "10:15:29"))
STUDENT_LEFT = report("IT4-101", "10:16:00", ("A-01", "EMPTY", "10:15:58"))


# ── 같은 방에 알림이 가는가 ──────────────────────────────────────


def test_first_report_sends_edge_status_then_seat_update(client):
    with client.websocket_connect("/ws/rooms/IT4-101") as ws:
        post(client, FIRST_REPORT)

        # 서버를 켠 뒤 첫 보고: 장치 연결(false → true)과 좌석(UNKNOWN → OCCUPIED)이 같은 version 1로 바뀐다.
        assert ws.receive_json() == {
            "event": "EDGE_STATUS_CHANGED",
            "room_id": "IT4-101",
            "version": 1,
            "edge_online": True,
        }
        assert ws.receive_json() == {
            "event": "SEAT_UPDATED",
            "room_id": "IT4-101",
            "version": 1,
            "available_seats": 0,
            "unknown_seats": 0,
            "congestion_level": "HIGH",
            "changes": [
                {"seat_id": "A-01", "prev_status": "UNKNOWN", "curr_status": "OCCUPIED", "reason": None,
                 "status_since": "2026-11-24T10:15:29+09:00", "last_observed_at": "2026-11-24T10:15:29+09:00"}
            ],
        }


def test_heartbeat_and_duplicate_report_send_nothing(client):
    with client.websocket_connect("/ws/rooms/IT4-101") as ws:
        post(client, FIRST_REPORT)
        ws.receive_json()  # EDGE_STATUS_CHANGED v1
        ws.receive_json()  # SEAT_UPDATED v1

        post(client, HEARTBEAT)      # 새 관측 없는 하트비트
        post(client, FIRST_REPORT)   # 같은 보고 재전송
        post(client, STUDENT_LEFT)   # 실제 변경

        # 앞의 두 보고가 알림을 보냈다면 여기서 그 메시지를 먼저 받아 실패한다.
        event = ws.receive_json()
        assert (event["event"], event["version"]) == ("SEAT_UPDATED", 2)
        assert event["changes"][0]["prev_status"] == "OCCUPIED"
        assert event["changes"][0]["curr_status"] == "EMPTY"
        assert event["available_seats"] == 1


def test_rejected_report_sends_nothing(client):
    with client.websocket_connect("/ws/rooms/IT4-101") as ws:
        assert post(client, FIRST_REPORT, key="wrong-key").status_code == 401
        unregistered_seat = report("IT4-101", "10:15:30", ("A-01", "OCCUPIED", "10:15:29"), ("Z-99", "EMPTY", "10:15:29"))
        assert post(client, unregistered_seat).status_code == 422
        post(client, FIRST_REPORT)

        assert ws.receive_json()["version"] == 1


def test_two_students_in_the_same_room_get_the_same_events(client):
    with (
        client.websocket_connect("/ws/rooms/IT4-101") as student_a,
        client.websocket_connect("/ws/rooms/IT4-101") as student_b,
    ):
        post(client, FIRST_REPORT)

        received_a = [student_a.receive_json(), student_a.receive_json()]
        received_b = [student_b.receive_json(), student_b.receive_json()]
        assert received_a == received_b
        assert [e["event"] for e in received_a] == ["EDGE_STATUS_CHANGED", "SEAT_UPDATED"]


def test_other_rooms_do_not_receive_the_events(client):
    with client.websocket_connect("/ws/rooms/IT4-102") as other_room:
        post(client, FIRST_REPORT)  # IT4-101의 변경
        post(client, report("IT4-102", "10:15:30", ("A-01", "EMPTY", "10:15:29")))  # IT4-102의 변경

        # IT4-101 알림이 섞여 왔다면 첫 메시지의 room_id가 IT4-101이다.
        first = other_room.receive_json()
        assert (first["room_id"], first["event"], first["version"]) == ("IT4-102", "EDGE_STATUS_CHANGED", 1)


# ── 연결의 시작과 끝 ─────────────────────────────────────────────


def test_unregistered_room_is_closed_with_4404(client):
    with pytest.raises(WebSocketDisconnect) as closed:
        with client.websocket_connect("/ws/rooms/IT4-999") as ws:
            ws.receive_json()

    assert closed.value.code == 4404


def test_connection_is_forgotten_after_the_student_leaves(client):
    connections: RoomConnections = client.app.state.connections

    with client.websocket_connect("/ws/rooms/IT4-101"):
        assert connections.count("IT4-101") == 1
    assert connections.count("IT4-101") == 0

    # 아무도 보고 있지 않아도 보고는 정상 처리된다.
    assert post(client, FIRST_REPORT).status_code == 200


# ── 재접속 복구 순서: WebSocket 연결 → 방 조회 → version 이하 이벤트 버림 ──


def apply_events_like_the_web(room: dict, events: list[dict]) -> tuple[dict, int]:
    """웹이 할 일을 흉내 낸다. 조회 결과에 이벤트를 차례로 반영하고, 버린 이벤트 수도 돌려준다."""
    room = copy.deepcopy(room)
    seats = {seat["seat_id"]: seat for seat in room["seats"]}
    discarded = 0
    for event in events:
        if event["version"] <= room["version"]:
            discarded += 1  # 조회 결과에 이미 들어 있는 변경
            continue
        if event["event"] == "EDGE_STATUS_CHANGED":
            room["edge_online"] = event["edge_online"]
        else:
            for change in event["changes"]:
                seat = seats[change["seat_id"]]
                seat["status"] = change["curr_status"]
                seat["reason"] = change["reason"]
                seat["status_since"] = change["status_since"]
                seat["last_observed_at"] = change["last_observed_at"]
            for key in ("available_seats", "unknown_seats", "congestion_level"):
                room[key] = event[key]
        room["version"] = event["version"]
    return room, discarded


def test_web_recovers_the_room_with_connect_then_fetch_then_skip_old_versions(client):
    with client.websocket_connect("/ws/rooms/IT4-102") as ws:  # 1. 연결부터
        # 연결과 조회 사이에 변경이 하나 일어났다. 이 알림은 조회보다 먼저 도착해 있다.
        post(client, report("IT4-102", "10:15:30", ("A-01", "OCCUPIED", "10:15:29"), ("A-02", "EMPTY", "10:15:28")))
        fetched = client.get("/api/v1/rooms/IT4-102").json()  # 2. 조회 (version 1)
        # 조회 뒤에 A2에 학생이 앉았다. A1은 사용 중 그대로이고 관측 시각만 새로워졌다.
        post(client, report("IT4-102", "10:15:50", ("A-01", "OCCUPIED", "10:15:49"), ("A-02", "OCCUPIED", "10:15:48")))

        events = [ws.receive_json() for _ in range(3)]  # v1 EDGE, v1 SEAT, v2 SEAT
        rebuilt, discarded = apply_events_like_the_web(fetched, events)  # 3. version 1 이하는 버림

    latest = client.get("/api/v1/rooms/IT4-102").json()
    assert fetched["version"] == 1
    assert discarded == 2
    # 상태가 그대로인 A1의 새 관측 시각은 이벤트로 오지 않는다. 웹이 30초마다 다시 조회해 맞추는 부분이다.
    assert rebuilt["seats"][0]["last_observed_at"] == "2026-11-24T10:15:29+09:00"
    assert latest["seats"][0]["last_observed_at"] == "2026-11-24T10:15:49+09:00"
    rebuilt["seats"][0]["last_observed_at"] = latest["seats"][0]["last_observed_at"]
    # 그 밖에는 이벤트로 다시 만든 화면이 새로 조회한 결과와 같다. 빠진 변경도, 두 번 반영된 변경도 없다.
    assert rebuilt == latest


# ── 알림을 잠금 안에서 보내는 이유 ───────────────────────────────


def test_events_reach_students_in_version_order_even_if_a_send_is_slow():
    """version 1 전송이 오래 걸려도 version 2가 먼저 도착하지 않는다.

    전송을 잠금 밖에서 했다면, 두 번째 보고가 첫 번째 전송이 끝나기 전에 반영·전송돼 [2, 1] 순서가 된다.
    """
    seat = seat_config("A-01", "A1")
    rooms = RoomRepository([RoomConfig(room_id="IT4-101", room_name="제1실습실", seats=[seat])],
                           started_at=datetime(2026, 11, 24, 10, 0, tzinfo=KST))
    first = StatusReport.model_validate(report("IT4-101", "10:15:30", ("A-01", "OCCUPIED", "10:15:29")))
    second = StatusReport.model_validate(report("IT4-101", "10:16:00", ("A-01", "EMPTY", "10:15:58")))
    delivered: list[int] = []

    async def slow_first_send(room_id, events) -> None:
        version = events[0].version
        await asyncio.sleep(0.05 if version == 1 else 0)  # version 1을 보내는 데만 오래 걸린다.
        delivered.append(version)

    async def two_reports_at_once() -> None:
        now = datetime(2026, 11, 24, 10, 16, tzinfo=KST)
        await asyncio.gather(
            apply_status_report(rooms, "IT4-101", first, received_at=now, publish=slow_first_send),
            apply_status_report(rooms, "IT4-101", second, received_at=now, publish=slow_first_send),
        )

    asyncio.run(two_reports_at_once())

    assert delivered == [1, 2]


# ── 느린 연결 처리 ───────────────────────────────────────────────


class FakeSocket:
    """broadcast가 쓰는 send_text·close만 흉내 낸 연결."""

    def __init__(self, delay: float = 0) -> None:
        self.delay = delay
        self.received: list[str] = []
        self.closed_with: int | None = None

    async def send_text(self, text: str) -> None:
        await asyncio.sleep(self.delay)
        self.received.append(text)

    async def close(self, code: int = 1000) -> None:
        self.closed_with = code


def test_slow_student_is_dropped_without_holding_up_the_others():
    connections = RoomConnections(send_timeout=0.05)
    fast, stuck = FakeSocket(), FakeSocket(delay=10)  # stuck은 10초 동안 받지 못한다.
    connections.add("IT4-101", fast)
    connections.add("IT4-101", stuck)
    events = [
        EdgeStatusChanged(room_id="IT4-101", version=1, edge_online=True),
        EdgeStatusChanged(room_id="IT4-101", version=2, edge_online=False),
    ]

    async def broadcast_and_time_it() -> float:
        loop = asyncio.get_running_loop()
        started = loop.time()
        await connections.broadcast("IT4-101", events)
        return loop.time() - started

    elapsed = asyncio.run(broadcast_and_time_it())

    assert elapsed < 1  # 10초를 기다리지 않고 제한 시간(0.05초) 근처에서 끝난다.
    assert [message.count('"version":1') for message in fast.received] == [1, 0]  # 순서대로 받았다.
    assert stuck.closed_with == SLOW_CLIENT_CLOSE_CODE
    assert connections.count("IT4-101") == 1  # 느린 연결만 빠졌다.
