from fastapi import APIRouter, HTTPException

from app.dependencies import RoomRepositoryDep
from app.schemas.rooms import RoomSnapshot
from app.services.rooms import get_room_snapshot

router = APIRouter(prefix="/api/v1/rooms", tags=["rooms"])


@router.get("/{room_id}", responses={404: {"description": "등록되지 않은 방"}})
async def read_room(room_id: str, rooms: RoomRepositoryDep) -> RoomSnapshot:
    snapshot = get_room_snapshot(rooms, room_id)
    if snapshot is None:
        raise HTTPException(status_code=404, detail="등록되지 않은 방입니다.")
    return snapshot
