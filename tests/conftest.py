from collections.abc import Iterator
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.repositories.rooms import ROOMS_CONFIG_PATH, RoomRepository

KST = timezone(timedelta(hours=9))
STARTED_AT = datetime(2026, 11, 17, 13, 50, tzinfo=KST)


@pytest.fixture
def rooms() -> RoomRepository:
    """설정 파일의 배치로 13:50에 막 시작한 서버의 방 저장소."""
    return RoomRepository.from_config_file(ROOMS_CONFIG_PATH, started_at=STARTED_AT)


@pytest.fixture
def client(rooms: RoomRepository) -> Iterator[TestClient]:
    """테스트마다 새 앱을 띄우고, 위 저장소를 주입한다."""
    with TestClient(create_app(lambda: rooms)) as client:
        yield client
