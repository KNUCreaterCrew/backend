from fastapi import APIRouter, Depends, HTTPException

from app.dependencies import (
    NowDep,
    RoomConnectionsDep,
    RoomRepositoryDep,
    verify_edge_api_key,
)
from app.schemas.reports import StatusReport, StatusReportAck
from app.services.reports import InvalidReport, RoomNotFound, apply_status_report

router = APIRouter(prefix="/api/v1/rooms", tags=["ingest"], dependencies=[Depends(verify_edge_api_key)])


@router.post(
    "/{room_id}/seats/status",
    responses={
        401: {"description": "장치 인증 키가 없거나 틀림"},
        404: {"description": "등록되지 않은 방"},
        422: {"description": "형식 오류, 등록되지 않은 좌석, 경로와 본문의 방 ID 불일치"},
    },
)
async def receive_status_report(
    room_id: str, report: StatusReport, rooms: RoomRepositoryDep, connections: RoomConnectionsDep, now: NowDep
) -> StatusReportAck:
    try:
        outcome = await apply_status_report(rooms, room_id, report, received_at=now, publish=connections.broadcast)
    except RoomNotFound:
        raise HTTPException(status_code=404, detail="등록되지 않은 방입니다.") from None
    except InvalidReport as error:
        raise HTTPException(status_code=422, detail=str(error)) from None
    return StatusReportAck(updated_count=len(outcome.changes), server_time=now)
