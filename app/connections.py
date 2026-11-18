"""방별로 열려 있는 WebSocket 연결을 관리한다.

    _rooms = {
        "IT4-101": {학생 A의 연결, 학생 B의 연결},
        "IT4-102": {학생 C의 연결},
    }

IT4-101에 변경이 생기면 A와 B에게만 보내고, C에게는 보내지 않는다.
연결 목록은 프로세스 메모리에 있으므로 uvicorn 워커는 1개로 실행한다.
"""

import asyncio
import contextlib
from collections.abc import Sequence

from fastapi import WebSocket

from app.schemas.events import RoomEvent

SEND_TIMEOUT_SECONDS = 1.0
"""학생 한 명에게 보내는 데 이보다 오래 걸리면 그 연결을 끊는다."""

SLOW_CLIENT_CLOSE_CODE = 1013
"""느린 연결을 끊을 때 쓰는 종료 코드(Try Again Later). 웹은 다시 연결하고 방 전체를 조회한다."""


class RoomConnections:
    def __init__(self, send_timeout: float = SEND_TIMEOUT_SECONDS) -> None:
        self._rooms: dict[str, set[WebSocket]] = {}
        self._send_timeout = send_timeout

    # ── 등록과 해제 ─────────────────────────────────────────────

    def add(self, room_id: str, websocket: WebSocket) -> None:
        self._rooms.setdefault(room_id, set()).add(websocket)

    def remove(self, room_id: str, websocket: WebSocket) -> None:
        sockets = self._rooms.get(room_id)
        if sockets is None:
            return
        sockets.discard(websocket)
        if not sockets:
            del self._rooms[room_id]

    def count(self, room_id: str) -> int:
        return len(self._rooms.get(room_id, ()))

    # ── 전송 ────────────────────────────────────────────────────

    async def broadcast(self, room_id: str, events: Sequence[RoomEvent]) -> None:
        """같은 방의 모든 연결에 이벤트를 차례대로 보낸다.

        학생마다 동시에 보내고(gather), 한 명당 최대 send_timeout초만 기다린다.
        그래서 학생이 몇 명이든 이 함수는 send_timeout초 안에 끝나고, 느린 학생 한 명이 다른 학생을 막지 않는다.
        """
        if not events:
            return
        messages = [event.model_dump_json() for event in events]
        # 보내는 도중 연결이 추가·삭제돼도 괜찮도록 지금 목록을 복사해서 쓴다.
        sockets = list(self._rooms.get(room_id, ()))
        await asyncio.gather(*(self._send(room_id, socket, messages) for socket in sockets))

    async def _send(self, room_id: str, websocket: WebSocket, messages: list[str]) -> None:
        try:
            async with asyncio.timeout(self._send_timeout):
                # 한 학생에게는 순서대로 보낸다. EDGE_STATUS_CHANGED 다음에 SEAT_UPDATED가 도착한다.
                for message in messages:
                    await websocket.send_text(message)
        except Exception:
            # 시간 초과, 이미 끊긴 연결 등 어떤 이유든 이 학생에게는 더 보내지 않는다.
            # 연결을 닫아 두면 웹이 다시 연결하면서 방 전체를 조회해 빠진 변경을 복구한다.
            self.remove(room_id, websocket)
            await self._close_quietly(websocket)

    async def _close_quietly(self, websocket: WebSocket) -> None:
        with contextlib.suppress(Exception):
            async with asyncio.timeout(self._send_timeout):
                await websocket.close(code=SLOW_CLIENT_CLOSE_CODE)
