from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app.main import create_app


@pytest.fixture
def client() -> Iterator[TestClient]:
    """테스트마다 새 앱과 새 저장소로 시작한다."""
    with TestClient(create_app()) as client:
        yield client
