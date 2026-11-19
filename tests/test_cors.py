"""다른 주소에 배포한 웹이 REST를 부를 수 있는지(CORS) 확인한다.

허용 출처는 CORS_ALLOW_ORIGINS로 받는다. 비어 있으면 다른 출처를 허용하지 않는다.
브라우저 WebSocket에는 CORS가 적용되지 않으므로 여기서는 REST만 본다.
"""

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.repositories.rooms import RoomRepository
from app.settings import CorsSettings
from tests.conftest import settings_with_test_key

WEB_ORIGIN = "https://zeroframe-web.example"
OTHER_ORIGIN = "https://other.example"


def client_with(rooms: RoomRepository, origins: list[str]) -> TestClient:
    return TestClient(
        create_app(
            lambda: rooms,
            settings_with_test_key,
            cors_settings_loader=lambda: CorsSettings(_env_file=None, cors_allow_origins=origins),
        )
    )


@pytest.fixture
def allowed(rooms) -> Iterator[TestClient]:
    with client_with(rooms, [WEB_ORIGIN]) as client:
        yield client


@pytest.fixture
def unconfigured(rooms) -> Iterator[TestClient]:
    with client_with(rooms, []) as client:
        yield client


def preflight(client: TestClient, origin: str, method: str = "GET"):
    return client.options(
        "/api/v1/rooms",
        headers={"Origin": origin, "Access-Control-Request-Method": method},
    )


@pytest.mark.parametrize("path", ["/api/v1/rooms", "/api/v1/rooms/IT4-101"])
def test_allowed_origin_can_read_the_response(allowed, path):
    response = allowed.get(path, headers={"Origin": WEB_ORIGIN})

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == WEB_ORIGIN


def test_allowed_origin_can_read_unregistered_room_404(allowed):
    """웹은 방 조회 404로 "방 없음"을 판단한다. 헤더가 없으면 브라우저가 응답을 읽지 못해 연결 실패로 보고 재시도한다."""
    response = allowed.get("/api/v1/rooms/unregistered", headers={"Origin": WEB_ORIGIN})

    assert response.status_code == 404
    assert response.headers["access-control-allow-origin"] == WEB_ORIGIN


def test_other_origin_gets_no_cors_header(allowed):
    response = allowed.get("/api/v1/rooms", headers={"Origin": OTHER_ORIGIN})

    assert "access-control-allow-origin" not in response.headers


def test_no_origin_is_allowed_without_the_setting(unconfigured):
    response = unconfigured.get("/api/v1/rooms", headers={"Origin": WEB_ORIGIN})

    assert response.status_code == 200
    assert "access-control-allow-origin" not in response.headers


def test_preflight_from_allowed_origin_allows_get(allowed):
    response = preflight(allowed, WEB_ORIGIN)

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == WEB_ORIGIN
    assert "GET" in response.headers["access-control-allow-methods"]


def test_preflight_from_other_origin_is_refused(allowed):
    response = preflight(allowed, OTHER_ORIGIN)

    assert response.status_code == 400
    assert "access-control-allow-origin" not in response.headers


def test_preflight_for_post_is_refused(allowed):
    """장치 보고(POST)는 브라우저가 보내는 요청이 아니므로 웹 출처에도 열지 않는다."""
    response = preflight(allowed, WEB_ORIGIN, method="POST")

    assert response.status_code == 400
    assert "POST" not in response.headers.get("access-control-allow-methods", "")


def test_preflight_without_the_setting_gets_no_cors_header(unconfigured):
    response = preflight(unconfigured, WEB_ORIGIN)

    assert "access-control-allow-origin" not in response.headers
