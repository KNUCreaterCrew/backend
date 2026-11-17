from datetime import datetime

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.models.rooms import Room, Seat, SeatLayout, SeatStatus
from app.repositories.rooms import RoomRepository
from app.services.rooms import congestion_level


def test_room_snapshot_matches_the_four_example_seats(client):
    response = client.get("/api/v1/rooms/IT4-101")

    assert response.status_code == 200
    room = response.json()
    seats = {seat["seat_id"]: seat for seat in room["seats"]}
    assert room["room_id"] == "IT4-101"
    assert room["edge_online"] is True
    assert {seat_id: seat["status"] for seat_id, seat in seats.items()} == {
        "A-01": "EMPTY",
        "A-02": "OCCUPIED",
        "B-01": "AWAY",
        "B-02": "UNKNOWN",
    }
    assert room["total_seats"] == len(room["seats"]) == 4
    assert room["available_seats"] == 1
    assert room["unknown_seats"] == 1
    assert room["congestion_level"] == "MODERATE"
    assert seats["A-01"]["has_outlet"] is True
    assert seats["A-01"]["layout"] == {"x": 0, "y": 0, "width": 64, "height": 48}
    assert seats["B-02"]["last_observed_at"] is None


def test_unregistered_room_returns_404(client):
    response = client.get("/api/v1/rooms/unregistered")

    assert response.status_code == 404


def test_app_reads_rooms_from_the_injected_repository():
    seat = Seat(
        seat_id="A-01",
        label="A1",
        status=SeatStatus.OCCUPIED,
        status_since=datetime.fromisoformat("2026-11-24T10:15:29+09:00"),
        last_observed_at=datetime.fromisoformat("2026-11-24T10:15:29+09:00"),
        has_outlet=True,
        is_window=True,
        layout=SeatLayout(x=120, y=80, width=64, height=48),
    )
    room = Room(room_id="TEST-1", room_name="테스트실", edge_online=True, seats=(seat,))

    with TestClient(create_app(lambda: RoomRepository([room]))) as client:
        injected = client.get("/api/v1/rooms/TEST-1")
        example = client.get("/api/v1/rooms/IT4-101")

    assert injected.status_code == 200
    assert injected.json()["total_seats"] == 1
    assert injected.json()["available_seats"] == 0
    assert injected.json()["congestion_level"] == "HIGH"
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
