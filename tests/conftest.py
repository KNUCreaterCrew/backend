from collections.abc import Iterator
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.repositories.rooms import ROOMS_CONFIG_PATH, RoomRepository
from app.settings import Settings

KST = timezone(timedelta(hours=9))
STARTED_AT = datetime(2026, 11, 17, 13, 50, tzinfo=KST)
TEST_EDGE_API_KEY = "test-edge-key"


def settings_with_test_key() -> Settings:
    return Settings(edge_api_key=TEST_EDGE_API_KEY)


class FakeClock:
    """테스트가 직접 옮기는 서버 시계."""

    def __init__(self, now: datetime) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock(STARTED_AT)


@pytest.fixture
def rooms() -> RoomRepository:
    """설정 파일의 배치로 13:50에 막 시작한 서버의 방 저장소."""
    return RoomRepository.from_config_file(ROOMS_CONFIG_PATH, started_at=STARTED_AT)


@pytest.fixture
def client(rooms: RoomRepository, clock: FakeClock) -> Iterator[TestClient]:
    """테스트마다 새 앱을 띄우고, 위 저장소와 시계, 테스트용 장치 키를 주입한다."""
    with TestClient(create_app(lambda: rooms, settings_with_test_key, clock)) as client:
        yield client
