import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services.rooms import congestion_level


def test_room_snapshot_matches_the_four_example_seats():
    with TestClient(app) as client:
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


def test_unregistered_room_returns_404():
    with TestClient(app) as client:
        response = client.get("/api/v1/rooms/unregistered")

    assert response.status_code == 404


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
