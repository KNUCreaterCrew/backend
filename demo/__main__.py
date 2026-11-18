"""카메라 없이 시연 흐름을 실제 서버로 재현한다.

    터미널 1:  EDGE_API_KEY=local-dev-key uv run uvicorn app.main:app
    터미널 2:  uv run python -m demo

이 스크립트가 Vision 장치(보고 전송)와 학생의 웹(WebSocket 연결·조회)을 함께 흉내 낸다.
보고에는 좌석 메타데이터만 담기고 영상·이미지는 없다. 장치 끊김을 기다리느라 1분 남짓 걸린다.
"""

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import UTC, datetime

from websockets.exceptions import WebSocketException
from websockets.sync.client import ClientConnection, connect

from demo.runner import ROOM_ID, StepResult, run_scenario


class ServerDriver:
    """실제 서버에 HTTP로 보고하고, WebSocket으로 이벤트를 받는다. 시간은 실제로 기다린다."""

    def __init__(self, base_url: str, api_key: str, ws: ClientConnection) -> None:
        self.base_url = base_url
        self.api_key = api_key
        self.ws = ws
        self.start = datetime.now(UTC)
        self._started = time.monotonic()

    def wait_until(self, seconds: float) -> None:
        remaining = self._started + seconds - time.monotonic()
        if remaining > 0:
            time.sleep(remaining)

    def send(self, report: dict) -> dict:
        request = urllib.request.Request(
            f"{self.base_url}/api/v1/rooms/{ROOM_ID}/seats/status",
            data=json.dumps(report).encode(),
            headers={"Content-Type": "application/json", "X-Edge-Api-Key": self.api_key},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=5) as response:
            return json.load(response)

    def fetch(self) -> dict:
        with urllib.request.urlopen(f"{self.base_url}/api/v1/rooms/{ROOM_ID}", timeout=5) as response:
            return json.load(response)

    def receive(self, count: int) -> list[dict]:
        # 장치 끊김은 서버가 1초마다 확인하므로 조금 늦게 올 수 있다. 넉넉히 10초까지 기다린다.
        return [json.loads(self.ws.recv(timeout=10)) for _ in range(count)]

    def unexpected_event(self) -> dict | None:
        # 알림이 없어야 하는 단계: 1초 동안 아무것도 오지 않으면 통과다.
        try:
            return json.loads(self.ws.recv(timeout=1))
        except TimeoutError:
            return None


# ── 출력 ────────────────────────────────────────────────────────


def describe(result: StepResult) -> str:
    room = result.room
    events = ", ".join(f"{e['event']} v{e['version']}" for e in result.events) or "없음"
    seats = " ".join(f"{s['label']}={s['status']}" for s in room["seats"])
    mark = "✅" if result.ok else "❌"
    lines = [
        f"{mark} +{result.at:>3g}s  {result.title}",
        f"        알림: {events}",
        (
            f"        조회: 빈자리 {room['available_seats']} / 전체 {room['total_seats']}석 · "
            f"확인 불가 {room['unknown_seats']}석 · {room['congestion_level']} · "
            f"장치 {'연결' if room['edge_online'] else '끊김'} · version {room['version']}"
        ),
        f"        좌석: {seats}",
    ]
    lines += [f"        ⚠ {problem}" for problem in result.problems]
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(prog="python -m demo", description=__doc__.splitlines()[0])
    parser.add_argument("--base-url", default="http://127.0.0.1:8000", help="백엔드 주소")
    parser.add_argument("--key", default=os.environ.get("EDGE_API_KEY"),
                        help="장치 인증 키 (기본값: 환경 변수 EDGE_API_KEY, 없으면 .env)")
    args = parser.parse_args()

    api_key = args.key
    if not api_key:
        from app.settings import Settings  # .env에서 서버와 같은 키를 읽는다.
        api_key = Settings().edge_api_key.get_secret_value()

    base_url = args.base_url.rstrip("/")
    ws_url = base_url.replace("http://", "ws://", 1).replace("https://", "wss://", 1)
    print(f"{base_url} 의 {ROOM_ID}에서 시연 흐름을 재현합니다. 장치 끊김을 기다리느라 1분 남짓 걸립니다.\n")

    try:
        # 웹의 시작 순서대로 WebSocket부터 연결한다. 방 조회는 run_scenario가 연결 뒤에 한다.
        with connect(f"{ws_url}/ws/rooms/{ROOM_ID}") as ws:
            driver = ServerDriver(base_url, api_key, ws)
            results = run_scenario(driver, on_step=lambda result: print(describe(result), flush=True))
    except urllib.error.HTTPError as error:
        print(f"\n보고가 거절됐습니다: HTTP {error.code} {error.read().decode()}")
        print("키가 서버의 EDGE_API_KEY와 같은지 확인하세요.")
        return 1
    except TimeoutError:
        print("\n기다리던 알림이 오지 않았습니다.")
        return 1
    except (OSError, WebSocketException) as error:
        print(f"서버에 연결하지 못했습니다: {error}\n서버를 먼저 실행했는지, 주소가 맞는지 확인하세요.")
        return 2

    failed = [result for result in results if not result.ok]
    print(f"\n{len(results) - len(failed)}/{len(results)} 단계가 기대와 일치합니다.")
    if not results[0].ok:
        print("첫 조회부터 다릅니다. 이전 실행의 상태가 메모리에 남아 있으니 서버를 다시 시작한 뒤 실행하세요.")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
