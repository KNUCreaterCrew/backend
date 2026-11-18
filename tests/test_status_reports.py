"""장치의 상태 보고가 방 조회에 반영되는지 확인한다.

앞부분은 공통 연동 명세(INTERFACES.md)의 한 좌석 예시를 그대로 재현하고,
뒷부분은 예시 설정 파일의 네 좌석 방(IT4-101)으로 중복·뒤늦은·잘못된 보고를 확인한다.
"""

import asyncio
from datetime import datetime

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.models.rooms import RoomConfig, SeatStatus
from app.repositories.rooms import RoomRepository
from app.schemas.reports import StatusReport
from app.services.reports import apply_status_report
from tests.conftest import (
    KST,
    STARTED_AT,
    TEST_EDGE_API_KEY,
    FakeClock,
    settings_with_test_key,
)

URL = "/api/v1/rooms/IT4-101/seats/status"


def kst(hhmmss: str, day: int = 24) -> datetime:
    hour, minute, second = map(int, hhmmss.split(":"))
    return datetime(2026, 11, day, hour, minute, second, tzinfo=KST)


def report(timestamp: str, *seats: dict, room_id: str = "IT4-101") -> dict:
    return {
        "room_id": room_id,
        "timestamp": timestamp,
        "inference_fps": 2.1,
        "saved_frames_count": 0,
        "seats": list(seats),
    }


def seat(seat_id: str, status: str, last_observed_at: str | None = None, reason: str | None = None) -> dict:
    body = {"seat_id": seat_id, "status": status, "confidence": None}
    if last_observed_at is not None:
        body["last_observed_at"] = last_observed_at
    if reason is not None:
        body["reason"] = reason
    return body


def post(client: TestClient, body: dict, key: str | None = TEST_EDGE_API_KEY, url: str = URL):
    headers = {} if key is None else {"X-Edge-Api-Key": key}
    return client.post(url, json=body, headers=headers)


# ── 공통 명세의 한 좌석 예시 ─────────────────────────────────────────


@pytest.fixture
def spec_client() -> TestClient:
    """명세 예시와 같은 한 좌석 방. 서버 시계는 테스트가 옮긴다."""
    seat_config = {"seat_id": "A-01", "label": "A1", "has_outlet": True, "is_window": True,
                   "layout": {"x": 120, "y": 80, "width": 64, "height": 48}}
    rooms = RoomRepository(
        [RoomConfig(room_id="IT4-101", room_name="제1실습실", seats=[seat_config])],
        started_at=kst("10:00:00"),
    )
    clock = FakeClock(kst("10:00:00"))
    with TestClient(create_app(lambda: rooms, settings_with_test_key, clock)) as client:
        client.clock = clock
        client.rooms = rooms
        yield client


SPEC_FIRST_REPORT = {
    "room_id": "IT4-101",
    "timestamp": "2026-11-24T10:15:30+09:00",
    "inference_fps": 2.1,
    "saved_frames_count": 0,
    "seats": [{"seat_id": "A-01", "status": "OCCUPIED", "confidence": None, "decision_source": "YOLO",
               "last_observed_at": "2026-11-24T10:15:29+09:00"}],
}

SPEC_HEARTBEAT = {
    **SPEC_FIRST_REPORT,
    "timestamp": "2026-11-24T10:15:40+09:00",
    "inference_fps": 2.0,
}

SPEC_ROOM_AFTER_FIRST_REPORT = {
    "room_id": "IT4-101",
    "room_name": "제1실습실",
    "total_seats": 1,
    "available_seats": 0,
    "unknown_seats": 0,
    "congestion_level": "HIGH",
    "edge_online": True,
    "version": 1,
    "seats": [{"seat_id": "A-01", "label": "A1", "status": "OCCUPIED", "reason": None,
               "status_since": "2026-11-24T10:15:29+09:00", "last_observed_at": "2026-11-24T10:15:29+09:00",
               "has_outlet": True, "is_window": True, "layout": {"x": 120, "y": 80, "width": 64, "height": 48}}],
}


def test_first_report_matches_the_spec_example(spec_client):
    spec_client.clock.now = datetime(2026, 11, 24, 10, 15, 30, 112000, tzinfo=KST)

    response = post(spec_client, SPEC_FIRST_REPORT)

    assert response.status_code == 200
    ack = response.json()
    assert ack["ok"] is True
    assert ack["updated_count"] == 1
    assert datetime.fromisoformat(ack["server_time"]) == spec_client.clock.now
    assert spec_client.get("/api/v1/rooms/IT4-101").json() == SPEC_ROOM_AFTER_FIRST_REPORT


def test_heartbeat_without_new_observation_keeps_the_last_observed_time(spec_client):
    spec_client.clock.now = kst("10:15:30")
    post(spec_client, SPEC_FIRST_REPORT)
    spec_client.clock.now = datetime(2026, 11, 24, 10, 15, 40, 105000, tzinfo=KST)

    response = post(spec_client, SPEC_HEARTBEAT)

    assert response.json()["updated_count"] == 0
    # 조회 결과는 첫 보고 직후와 같다. 마지막 확인 시각은 10:15:29, version도 1 그대로다.
    assert spec_client.get("/api/v1/rooms/IT4-101").json() == SPEC_ROOM_AFTER_FIRST_REPORT
    # 대신 서버는 이 보고를 받은 시각을 장치 연결 판단의 기준으로 남긴다.
    assert spec_client.rooms.find("IT4-101").last_report_at == spec_client.clock.now


# ── 네 좌석 방 ─────────────────────────────────────────────────────


def room(client: TestClient) -> dict:
    return client.get("/api/v1/rooms/IT4-101").json()


def statuses(room_body: dict) -> dict[str, str]:
    return {s["seat_id"]: s["status"] for s in room_body["seats"]}


FOUR_SEATS = report(
    "2026-11-17T14:02:10+09:00",
    seat("A-01", "EMPTY", "2026-11-17T14:02:05+09:00"),
    seat("A-02", "OCCUPIED", "2026-11-17T14:02:08+09:00"),
    seat("B-01", "AWAY", "2026-11-17T14:02:09+09:00"),
    seat("B-02", "UNKNOWN", reason="OCCLUDED"),
)


def test_four_seat_report_produces_the_project_example_summary(client):
    response = post(client, FOUR_SEATS)

    after = room(client)
    assert response.json()["updated_count"] == 4
    assert statuses(after) == {"A-01": "EMPTY", "A-02": "OCCUPIED", "B-01": "AWAY", "B-02": "UNKNOWN"}
    assert (after["total_seats"], after["available_seats"], after["unknown_seats"]) == (4, 1, 1)
    assert after["congestion_level"] == "MODERATE"
    assert after["edge_online"] is True
    assert after["version"] == 1


def test_same_report_twice_changes_nothing_the_second_time(client):
    post(client, FOUR_SEATS)
    first = room(client)

    response = post(client, FOUR_SEATS)

    assert response.status_code == 200
    assert response.json()["updated_count"] == 0
    assert room(client) == first


def test_seats_missing_from_the_report_stay_as_they_were(client):
    response = post(client, report("2026-11-17T14:00:00+09:00", seat("A-01", "EMPTY", "2026-11-17T13:59:55+09:00")))

    seats = {s["seat_id"]: s for s in room(client)["seats"]}
    assert response.json()["updated_count"] == 1
    assert seats["A-01"]["status"] == "EMPTY"
    for seat_id in ("A-02", "B-01", "B-02"):
        assert seats[seat_id]["status"] == "UNKNOWN"
        assert seats[seat_id]["reason"] == "EDGE_OFFLINE"
        assert datetime.fromisoformat(seats[seat_id]["status_since"]) == STARTED_AT


def test_status_since_follows_the_observation_or_the_report_time(client):
    post(client, report("2026-11-17T14:00:00+09:00", seat("A-01", "OCCUPIED", "2026-11-17T13:59:58+09:00")))
    after_occupied = room(client)["seats"][0]

    # 같은 상태가 이어지면 status_since는 그대로, 마지막 확인 시각만 새 관측으로 바뀐다.
    post(client, report("2026-11-17T14:00:10+09:00", seat("A-01", "OCCUPIED", "2026-11-17T14:00:09+09:00")))
    still_occupied = room(client)["seats"][0]

    # 확인 불가가 되면 status_since는 보고 시각, 마지막 확인 시각은 마지막 유효 관측으로 남는다.
    post(client, report("2026-11-17T14:00:45+09:00", seat("A-01", "UNKNOWN", reason="STALE_OBSERVATION")))
    unknown = room(client)["seats"][0]

    assert datetime.fromisoformat(after_occupied["status_since"]) == kst("13:59:58", day=17)
    assert datetime.fromisoformat(still_occupied["status_since"]) == kst("13:59:58", day=17)
    assert datetime.fromisoformat(still_occupied["last_observed_at"]) == kst("14:00:09", day=17)
    assert datetime.fromisoformat(unknown["status_since"]) == kst("14:00:45", day=17)
    assert datetime.fromisoformat(unknown["last_observed_at"]) == kst("14:00:09", day=17)


def test_reason_change_alone_counts_as_a_change_but_keeps_status_since(client):
    post(client, report("2026-11-17T13:59:50+09:00", seat("A-01", "OCCUPIED", "2026-11-17T13:59:49+09:00")))
    post(client, report("2026-11-17T14:00:00+09:00", seat("A-01", "UNKNOWN", reason="OCCLUDED")))

    response = post(client, report("2026-11-17T14:00:30+09:00", seat("A-01", "UNKNOWN", reason="STALE_OBSERVATION")))

    a1 = room(client)["seats"][0]
    assert response.json()["updated_count"] == 1
    assert a1["reason"] == "STALE_OBSERVATION"
    # 확인 불가가 된 14:00:00부터 사유만 바뀌었으므로 상태 변경 시각은 그대로다.
    assert datetime.fromisoformat(a1["status_since"]) == kst("14:00:00", day=17)
    assert room(client)["version"] == 3


def test_late_report_is_applied_and_the_next_report_corrects_it(client):
    """명세는 장치 timestamp로 보고를 버리지 않는다. 늦은 보고가 잠깐 반영돼도 다음 보고가 바로잡는다."""
    older = report("2026-11-17T14:00:10+09:00", seat("A-01", "EMPTY", "2026-11-17T14:00:08+09:00"))
    newer = report("2026-11-17T14:00:20+09:00", seat("A-01", "OCCUPIED", "2026-11-17T14:00:19+09:00"))
    next_heartbeat = report("2026-11-17T14:00:30+09:00", seat("A-01", "OCCUPIED", "2026-11-17T14:00:19+09:00"))

    post(client, newer)
    post(client, older)
    late = room(client)
    post(client, next_heartbeat)
    corrected = room(client)

    # 어느 시점이든 좌석 목록과 집계는 같은 상태에서 나온다.
    assert statuses(late)["A-01"] == "EMPTY"
    assert late["available_seats"] == 1
    assert statuses(corrected)["A-01"] == "OCCUPIED"
    assert corrected["available_seats"] == 0
    assert datetime.fromisoformat(corrected["seats"][0]["last_observed_at"]) == kst("14:00:19", day=17)


def test_server_records_when_it_received_the_report(client, clock, rooms):
    clock.now = kst("14:00:01", day=17)

    response = post(client, FOUR_SEATS)

    assert datetime.fromisoformat(response.json()["server_time"]) == clock.now
    assert rooms.find("IT4-101").last_report_at == clock.now


# ── 반영하지 않는 보고 ──────────────────────────────────────────────


@pytest.mark.parametrize("key", [None, "wrong-key"])
def test_missing_or_wrong_key_is_rejected(client, key):
    before = room(client)

    response = post(client, FOUR_SEATS, key=key)

    assert response.status_code == 401
    assert room(client) == before


def test_key_is_checked_before_the_body(client):
    assert post(client, {"not": "a report"}, key="wrong-key").status_code == 401


def test_unregistered_room_returns_404(client):
    body = report("2026-11-17T14:00:00+09:00", seat("A-01", "EMPTY", "2026-11-17T14:00:00+09:00"), room_id="IT4-999")

    assert post(client, body, url="/api/v1/rooms/IT4-999/seats/status").status_code == 404


INVALID_REPORTS = {
    "등록되지 않은 좌석이 섞임": report(
        "2026-11-17T14:00:00+09:00",
        seat("A-01", "EMPTY", "2026-11-17T13:59:55+09:00"),
        seat("Z-99", "EMPTY", "2026-11-17T13:59:55+09:00"),
    ),
    "경로와 본문의 방 ID가 다름": report(
        "2026-11-17T14:00:00+09:00", seat("A-01", "EMPTY", "2026-11-17T13:59:55+09:00"), room_id="IT4-102"
    ),
    "UNKNOWN이 아닌데 사유가 있음": report(
        "2026-11-17T14:00:00+09:00", seat("A-01", "OCCUPIED", "2026-11-17T13:59:55+09:00", reason="OCCLUDED")
    ),
    "같은 좌석이 두 번 들어 있음": report(
        "2026-11-17T14:00:00+09:00",
        seat("A-01", "EMPTY", "2026-11-17T13:59:55+09:00"),
        seat("A-01", "OCCUPIED", "2026-11-17T13:59:55+09:00"),
    ),
    "시간대가 없는 시각": report("2026-11-17T14:00:00", seat("A-01", "EMPTY", "2026-11-17T13:59:55+09:00")),
    "알 수 없는 상태 코드": report("2026-11-17T14:00:00+09:00", seat("A-01", "RESERVED", "2026-11-17T13:59:55+09:00")),
    "좌석이 하나도 없음": report("2026-11-17T14:00:00+09:00"),
}


@pytest.mark.parametrize("body", INVALID_REPORTS.values(), ids=INVALID_REPORTS.keys())
def test_invalid_report_is_rejected_without_partial_changes(client, rooms, body):
    before = room(client)

    response = post(client, body)

    assert response.status_code == 422
    assert room(client) == before
    assert rooms.find("IT4-101").last_report_at is None


# ── 방별 잠금 ──────────────────────────────────────────────────────


def test_report_waits_while_the_room_is_locked(rooms):
    """연결 감시(#13) 같은 다른 작업이 방을 잡고 있으면, 보고는 그 작업이 끝난 뒤에 반영된다."""
    body = StatusReport.model_validate(
        report("2026-11-17T14:00:00+09:00", seat("A-01", "EMPTY", "2026-11-17T13:59:55+09:00"))
    )
    room_state = rooms.find("IT4-101")

    async def scenario() -> None:
        async with room_state.lock:
            task = asyncio.create_task(apply_status_report(rooms, "IT4-101", body, received_at=STARTED_AT))
            await asyncio.sleep(0)
            assert not task.done()
            assert room_state.seats["A-01"].status == SeatStatus.UNKNOWN
        outcome = await task
        assert outcome.version == 1
        assert room_state.seats["A-01"].status == SeatStatus.EMPTY

    asyncio.run(scenario())
