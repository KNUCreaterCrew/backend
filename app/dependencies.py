import secrets
from datetime import datetime
from typing import Annotated

from fastapi import Depends, Header, HTTPException, Request
from starlette.requests import HTTPConnection

from app.connections import RoomConnections
from app.repositories.rooms import RoomRepository

# HTTPConnection은 HTTP 요청과 WebSocket 연결의 공통 부모다.
# Request로 받으면 WebSocket 엔드포인트에서는 쓸 수 없으므로, 양쪽이 함께 쓰는 의존성은 이것으로 받는다.


def get_room_repository(connection: HTTPConnection) -> RoomRepository:
    return connection.app.state.rooms


def get_room_connections(connection: HTTPConnection) -> RoomConnections:
    return connection.app.state.connections


def get_now(request: Request) -> datetime:
    return request.app.state.clock()


async def verify_edge_api_key(
    request: Request, x_edge_api_key: Annotated[str | None, Header()] = None
) -> None:
    """장치 인증 키를 확인한다. 본문 검사보다 먼저 실행돼, 키가 틀리면 본문 내용과 상관없이 401이다."""
    expected = request.app.state.settings.edge_api_key.get_secret_value()
    if x_edge_api_key is None or not secrets.compare_digest(x_edge_api_key.encode(), expected.encode()):
        raise HTTPException(status_code=401, detail="장치 인증 키가 없거나 올바르지 않습니다.")


RoomRepositoryDep = Annotated[RoomRepository, Depends(get_room_repository)]
RoomConnectionsDep = Annotated[RoomConnections, Depends(get_room_connections)]
NowDep = Annotated[datetime, Depends(get_now)]
