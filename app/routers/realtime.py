from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse

from app.dependencies import RoomConnectionsDep, RoomRepositoryDep

router = APIRouter(tags=["realtime"])


@router.websocket("/ws/rooms/{room_id}")
async def room_updates(
    websocket: WebSocket, room_id: str, rooms: RoomRepositoryDep, connections: RoomConnectionsDep
) -> None:
    """한 방의 변경 알림을 받는 연결. 서버가 보내기만 하고, 웹이 보내는 메시지는 쓰지 않는다."""
    # 1. 없는 방이면 연결을 수락하지 않고 HTTP 404로 거절한다.
    #    수락한 뒤 종료 코드(4404)로 닫으면, 배포 서버(Render)의 앞단 프록시가 그 닫힘 프레임을 전달하지 않아
    #    웹은 20초 동안 아무 응답 없이 기다리다 이유 없이 끊겼다(#32). 일반 HTTP 응답은 프록시를 그대로 지난다.
    #    브라우저는 거절 이유를 보여 주지 않으므로, 웹은 연결 직후 하는 방 조회의 404로 판단한다.
    if rooms.find(room_id) is None:
        await websocket.send_denial_response(
            JSONResponse({"detail": "등록되지 않은 방입니다."}, status_code=404)
        )
        return

    # 2. 연결 수락. 이 시점에 웹 쪽에서 onopen이 불린다.
    await websocket.accept()

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
