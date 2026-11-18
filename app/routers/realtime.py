from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.dependencies import RoomConnectionsDep, RoomRepositoryDep

router = APIRouter(tags=["realtime"])

UNKNOWN_ROOM_CLOSE_CODE = 4404
"""등록되지 않은 방으로 연결하면 이 코드로 닫는다. 4000~4999는 앱이 정해 쓰는 범위다."""


@router.websocket("/ws/rooms/{room_id}")
async def room_updates(
    websocket: WebSocket, room_id: str, rooms: RoomRepositoryDep, connections: RoomConnectionsDep
) -> None:
    """한 방의 변경 알림을 받는 연결. 서버가 보내기만 하고, 웹이 보내는 메시지는 쓰지 않는다."""
    # 1. 연결 수락. 이 시점에 웹 쪽에서 onopen이 불린다.
    await websocket.accept()

    # 2. 없는 방이면 이유를 알 수 있는 코드로 닫는다. (수락 전에 닫으면 웹은 이유 없이 실패만 본다.)
    if rooms.find(room_id) is None:
        await websocket.close(code=UNKNOWN_ROOM_CLOSE_CODE, reason="등록되지 않은 방입니다.")
        return

    # 3. 이 방의 알림 대상으로 등록한다.
    connections.add(room_id, websocket)
    try:
        # 4. 연결이 끊길 때까지 기다린다. 알림은 broadcast가 이 연결로 따로 보낸다.
        #    receive_text()는 웹이 보낸 메시지를 기다리다가, 연결이 끊기면 WebSocketDisconnect를 던진다.
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        # 5. 어떻게 끝나든(정상 종료, 네트워크 끊김, 서버 종료) 목록에서 뺀다.
        connections.remove(room_id, websocket)
