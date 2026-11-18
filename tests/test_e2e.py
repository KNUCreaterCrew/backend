"""시연 시나리오(demo/scenario.py)를 가짜 시계로 처음부터 끝까지 재현한다.

시연 스크립트(python -m demo)와 같은 시나리오·대조 규칙을 쓴다. 실제 서버에서는 1분 넘게 걸리는 흐름이
여기서는 시계를 옮기며 1초 안에 끝난다.
"""

from datetime import datetime, timedelta

from fastapi.testclient import TestClient

from app.main import create_app
from app.repositories.rooms import ROOMS_CONFIG_PATH, RoomRepository
from demo.runner import ROOM_ID, run_scenario
from demo.scenario import STEPS
from tests.conftest import KST, TEST_EDGE_API_KEY, FakeClock, settings_with_test_key

START = datetime(2026, 11, 24, 14, 0, tzinfo=KST)


class FakeTimeDriver:
    """TestClient로 보내고, 기다리는 대신 가짜 시계를 옮긴다."""

    def __init__(self, client: TestClient, ws, clock: FakeClock) -> None:
        self.client, self.ws, self.clock = client, ws, clock
        self.start = START

    def wait_until(self, seconds: float) -> None:
        # 서버 시계를 옮긴다. 감시 작업(0.01초 주기)이 바뀐 시계로 30초 경과를 판단한다.
        self.clock.now = self.start + timedelta(seconds=seconds)

    def send(self, report: dict) -> dict:
        response = self.client.post(f"/api/v1/rooms/{ROOM_ID}/seats/status", json=report,
                                    headers={"X-Edge-Api-Key": TEST_EDGE_API_KEY})
        assert response.status_code == 200, response.text
        return response.json()

    def fetch(self) -> dict:
        return self.client.get(f"/api/v1/rooms/{ROOM_ID}").json()

    def receive(self, count: int) -> list[dict]:
        return [self.ws.receive_json() for _ in range(count)]

    def unexpected_event(self) -> dict | None:
        # TestClient는 "잠시 기다렸다 없으면 포기"를 할 수 없다. 대신 이 단계에 이벤트가 잘못 나갔다면
        # 다음 단계가 그 이벤트를 먼저 받아 이벤트 이름이나 version 대조에서 실패한다.
        return None


def test_demo_scenario_from_first_look_to_reconnect():
    rooms = RoomRepository.from_config_file(ROOMS_CONFIG_PATH, started_at=START - timedelta(minutes=5))
    clock = FakeClock(START)
    app = create_app(lambda: rooms, settings_with_test_key, clock, edge_check_interval=0.01)

    with TestClient(app) as client, client.websocket_connect(f"/ws/rooms/{ROOM_ID}") as ws:
        results = run_scenario(FakeTimeDriver(client, ws, clock))

    assert len(results) == len(STEPS) + 1
    failures = {f"+{r.at:g}s {r.title}": r.problems for r in results if not r.ok}
    assert failures == {}
