"""방 목록 조회(GET /api/v1/rooms)를 확인한다.

방 두 개를 설정 파일 순서대로 둔다. LAB-B는 보고를 받다가 끊겼고, LAB-A는 장치가 연결돼 있다.

    10:15:40  LAB-B 보고: 두 좌석 모두 빈자리
    10:16:00  LAB-A 보고: 빈자리, 사용 중, 짐 있음, 가림
    10:16:10  LAB-B는 30초 동안 보고가 없어 오프라인 전환 → 두 좌석 확인 불가
"""

import asyncio
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.models.rooms import RoomConfig
from app.repositories.rooms import RoomRepository
from app.schemas.reports import StatusReport
from app.services.edge import mark_offline_if_silent
from app.services.reports import apply_status_report
from tests.conftest import KST, FakeClock, settings_with_test_key

T0 = datetime(2026, 11, 24, 10, 15, 40, tzinfo=KST)

SUMMARY_FIELDS = (
    "room_id", "room_name", "total_seats", "available_seats", "unknown_seats", "congestion_level", "edge_online",
)


def room_config(room_id: str, room_name: str, seat_ids: list[str]) -> RoomConfig:
    seats = [
        {"seat_id": seat_id, "label": seat_id.replace("-0", ""), "has_outlet": False, "is_window": False,
         "layout": {"x": 80 * index, "y": 0, "width": 64, "height": 48}}
        for index, seat_id in enumerate(seat_ids)
    ]
    return RoomConfig(room_id=room_id, room_name=room_name, seats=seats)


def report(room_id: str, at: datetime, *seats: dict) -> StatusReport:
    return StatusReport.model_validate({
        "room_id": room_id, "timestamp": at.isoformat(), "inference_fps": 2.0, "saved_frames_count": 0,
        "seats": list(seats),
    })


def seat(seat_id: str, status: str, observed: datetime | None = None, reason: str | None = None) -> dict:
    return {"seat_id": seat_id, "status": status, "confidence": None, "reason": reason,
            "last_observed_at": observed.isoformat() if observed else None}


async def ignore(room_id, events) -> None:
    """이 테스트는 알림을 보지 않는다."""


@pytest.fixture
def two_rooms() -> RoomRepository:
    """설정 순서가 LAB-B, LAB-A인 저장소. room_id 순 정렬과 구분되도록 일부러 거꾸로 둔다."""
    rooms = RoomRepository(
        [
            room_config("LAB-B", "제2실습실 (예시)", ["A-01", "A-02"]),
            room_config("LAB-A", "제1실습실 (예시)", ["A-01", "A-02", "B-01", "B-02"]),
        ],
        started_at=T0 - timedelta(minutes=10),
    )

    async def prepare() -> None:
        await apply_status_report(
            rooms, "LAB-B",
            report("LAB-B", T0, seat("A-01", "EMPTY", T0), seat("A-02", "EMPTY", T0)),
            received_at=T0, publish=ignore,
        )
        at_a = T0 + timedelta(seconds=20)
        await apply_status_report(
            rooms, "LAB-A",
            report("LAB-A", at_a, seat("A-01", "EMPTY", at_a), seat("A-02", "OCCUPIED", at_a),
                   seat("B-01", "AWAY", at_a), seat("B-02", "UNKNOWN", reason="OCCLUDED")),
            received_at=at_a, publish=ignore,
        )
        offline_at = T0 + timedelta(seconds=30)
        for room in rooms.all():
            await mark_offline_if_silent(room, clock=lambda: offline_at, publish=ignore)

    asyncio.run(prepare())
    return rooms


@pytest.fixture
def two_rooms_client(two_rooms) -> TestClient:
    clock = FakeClock(T0 + timedelta(seconds=30))
    with TestClient(create_app(lambda: two_rooms, settings_with_test_key, clock)) as client:
        yield client


def test_no_rooms_returns_an_empty_list():
    empty = RoomRepository([], started_at=T0)

    with TestClient(create_app(lambda: empty, settings_with_test_key)) as client:
        response = client.get("/api/v1/rooms")

    assert response.status_code == 200
    assert response.json() == []


def test_list_summarizes_each_room_in_config_order(two_rooms_client):
    response = two_rooms_client.get("/api/v1/rooms")

    assert response.status_code == 200
    assert response.json() == [
        {
            "room_id": "LAB-B",
            "room_name": "제2실습실 (예시)",
            "total_seats": 2,
            "available_seats": 0,
            "unknown_seats": 2,
            "congestion_level": "HIGH",
            "edge_online": False,
        },
        {
            "room_id": "LAB-A",
            "room_name": "제1실습실 (예시)",
            "total_seats": 4,
            "available_seats": 1,
            "unknown_seats": 1,
            "congestion_level": "MODERATE",
            "edge_online": True,
        },
    ]


def test_list_numbers_match_each_room_snapshot(two_rooms_client):
    listed = two_rooms_client.get("/api/v1/rooms").json()

    for item in listed:
        snapshot = two_rooms_client.get(f"/api/v1/rooms/{item['room_id']}").json()
        assert {field: snapshot[field] for field in SUMMARY_FIELDS} == item


def test_list_leaves_out_seats_and_version(two_rooms_client):
    for item in two_rooms_client.get("/api/v1/rooms").json():
        assert set(item) == set(SUMMARY_FIELDS)


def test_fresh_server_lists_the_example_room_as_offline(client):
    assert client.get("/api/v1/rooms").json() == [
        {
            "room_id": "IT4-101",
            "room_name": "제1실습실 (예시)",
            "total_seats": 4,
            "available_seats": 0,
            "unknown_seats": 4,
            "congestion_level": "HIGH",
            "edge_online": False,
        }
    ]


def test_trailing_slash_redirects_to_the_list(client):
    response = client.get("/api/v1/rooms/", follow_redirects=False)

    assert response.status_code == 307
    assert response.headers["location"].endswith("/api/v1/rooms")
