from datetime import datetime

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.main import create_app
from app.models.rooms import RoomConfig, SeatReason, SeatState, SeatStatus
from app.repositories.rooms import RoomRepository
from app.services.rooms import congestion_level
from tests.conftest import KST, STARTED_AT, settings_with_test_key


def at(hhmm: str) -> datetime:
    hour, minute = map(int, hhmm.split(":"))
    return datetime(2026, 11, 17, hour, minute, tzinfo=KST)


def apply_four_seat_example(rooms: RoomRepository) -> None:
    """네 좌석이 각각 빈자리·사용 중·짐 있음·확인 불가인 예시."""
    room = rooms.find("IT4-101")
    room.edge_online = True
    room.set_seat("A-01", SeatState(status=SeatStatus.EMPTY, status_since=at("14:00"), last_observed_at=at("14:02")))
    room.set_seat("A-02", SeatState(status=SeatStatus.OCCUPIED, status_since=at("13:55"), last_observed_at=at("14:02")))
    room.set_seat("B-01", SeatState(status=SeatStatus.AWAY, status_since=at("14:01"), last_observed_at=at("14:02")))
    room.set_seat(
        "B-02",
        SeatState(status=SeatStatus.UNKNOWN, reason=SeatReason.STALE_OBSERVATION, status_since=at("14:00")),
    )


def test_fresh_server_reports_every_seat_unknown(client):
    room = client.get("/api/v1/rooms/IT4-101").json()

    assert room["edge_online"] is False
    assert room["version"] == 0
    assert room["total_seats"] == room["unknown_seats"] == 4
    assert room["available_seats"] == 0
    assert room["congestion_level"] == "HIGH"
    for seat in room["seats"]:
        assert seat["status"] == "UNKNOWN"
        assert seat["reason"] == "EDGE_OFFLINE"
        assert seat["last_observed_at"] is None
        assert datetime.fromisoformat(seat["status_since"]) == STARTED_AT


def test_layout_comes_from_the_config_file(client):
    seats = {seat["seat_id"]: seat for seat in client.get("/api/v1/rooms/IT4-101").json()["seats"]}

    assert list(seats) == ["A-01", "A-02", "B-01", "B-02"]
    assert seats["A-01"]["label"] == "A1"
    assert seats["A-01"]["has_outlet"] is True
    assert seats["A-01"]["is_window"] is True
    assert seats["A-01"]["layout"] == {"x": 0, "y": 0, "width": 64, "height": 48}


def test_room_snapshot_matches_the_four_example_seats(rooms, client):
    apply_four_seat_example(rooms)

    room = client.get("/api/v1/rooms/IT4-101").json()

    seats = {seat["seat_id"]: seat for seat in room["seats"]}
    assert room["edge_online"] is True
    assert {seat_id: seat["status"] for seat_id, seat in seats.items()} == {
        "A-01": "EMPTY",
        "A-02": "OCCUPIED",
        "B-01": "AWAY",
        "B-02": "UNKNOWN",
    }
    assert room["total_seats"] == 4
    assert room["available_seats"] == 1
    assert room["unknown_seats"] == 1
    assert room["congestion_level"] == "MODERATE"
    assert seats["A-01"]["reason"] is None
    assert seats["B-02"]["reason"] == "STALE_OBSERVATION"
    assert seats["B-02"]["last_observed_at"] is None


def test_changing_one_seat_updates_the_list_and_summary_together(rooms, client):
    before = client.get("/api/v1/rooms/IT4-101").json()

    rooms.find("IT4-101").set_seat(
        "A-01", SeatState(status=SeatStatus.EMPTY, status_since=at("14:00"), last_observed_at=at("14:00"))
    )
    after = client.get("/api/v1/rooms/IT4-101").json()

    assert (before["available_seats"], before["unknown_seats"]) == (0, 4)
    assert (after["available_seats"], after["unknown_seats"]) == (1, 3)
    assert after["congestion_level"] == "MODERATE"
    assert after["seats"][0]["status"] == "EMPTY"
    assert after["seats"][0]["reason"] is None


def test_setting_an_unregistered_seat_is_rejected(rooms):
    with pytest.raises(KeyError):
        rooms.find("IT4-101").set_seat("Z-99", SeatState.unobserved(STARTED_AT))


def test_reason_is_only_allowed_for_unknown_seats():
    with pytest.raises(ValidationError):
        SeatState(status=SeatStatus.EMPTY, reason=SeatReason.OCCLUDED, status_since=STARTED_AT)


def test_config_rejects_duplicate_ids():
    seat = {"seat_id": "A-01", "label": "A1", "has_outlet": False, "is_window": False,
            "layout": {"x": 0, "y": 0, "width": 1, "height": 1}}
    with pytest.raises(ValidationError):
        RoomConfig(room_id="TEST-1", room_name="테스트실", seats=[seat, seat])

    room = RoomConfig(room_id="TEST-1", room_name="테스트실", seats=[seat])
    with pytest.raises(ValueError):
        RoomRepository([room, room], started_at=STARTED_AT)


def test_unregistered_room_returns_404(client):
    assert client.get("/api/v1/rooms/unregistered").status_code == 404


def test_app_reads_rooms_from_the_injected_repository():
    seat = {"seat_id": "A-01", "label": "A1", "has_outlet": True, "is_window": True,
            "layout": {"x": 120, "y": 80, "width": 64, "height": 48}}
    rooms = RoomRepository([RoomConfig(room_id="TEST-1", room_name="테스트실", seats=[seat])], started_at=STARTED_AT)

    with TestClient(create_app(lambda: rooms, settings_with_test_key)) as client:
        injected = client.get("/api/v1/rooms/TEST-1")
        example = client.get("/api/v1/rooms/IT4-101")

    assert injected.status_code == 200
    assert injected.json()["total_seats"] == 1
    assert example.status_code == 404


@pytest.mark.parametrize(
    ("available", "total", "expected"),
    [
        (0, 4, "HIGH"),
        (24, 100, "HIGH"),
        (25, 100, "MODERATE"),
        (59, 100, "MODERATE"),
        (60, 100, "LOW"),
        (4, 4, "LOW"),
    ],
)
def test_congestion_thresholds(available, total, expected):
    assert congestion_level(available, total) == expected
