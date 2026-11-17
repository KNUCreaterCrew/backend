from typing import Annotated

from fastapi import Depends, Request

from app.repositories.rooms import RoomRepository


def get_room_repository(request: Request) -> RoomRepository:
    return request.app.state.rooms


RoomRepositoryDep = Annotated[RoomRepository, Depends(get_room_repository)]
