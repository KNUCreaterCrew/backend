import secrets
from datetime import datetime
from typing import Annotated

from fastapi import Depends, Header, HTTPException, Request

from app.repositories.rooms import RoomRepository


def get_room_repository(request: Request) -> RoomRepository:
    return request.app.state.rooms


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
NowDep = Annotated[datetime, Depends(get_now)]
