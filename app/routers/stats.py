from datetime import date
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query

from app.clock import SEOUL
from app.dependencies import NowDep, RoomRepositoryDep, StatsStoreDep
from app.schemas.stats import DailyStats, WeeklyStats
from app.services.reports import RoomNotFound
from app.services.stats_query import DEFAULT_WEEKS, MAX_WEEKS, daily_stats, weekly_stats

router = APIRouter(prefix="/api/v1/rooms", tags=["stats"])

NOT_FOUND = {404: {"description": "등록되지 않은 방"}}


@router.get("/{room_id}/stats/daily", responses=NOT_FOUND)
async def read_daily_stats(
    room_id: str, rooms: RoomRepositoryDep, store: StatsStoreDep, now: NowDep,
    day: Annotated[date | None, Query(alias="date", description="한국 시간 날짜(YYYY-MM-DD). 생략하면 오늘")] = None,
) -> DailyStats:
    try:
        return await daily_stats(rooms, store, room_id, day or now.astimezone(SEOUL).date())
    except RoomNotFound:
        raise HTTPException(status_code=404, detail="등록되지 않은 방입니다.") from None


@router.get("/{room_id}/stats/weekly", responses=NOT_FOUND)
async def read_weekly_stats(
    room_id: str, rooms: RoomRepositoryDep, store: StatsStoreDep, now: NowDep,
    weeks: Annotated[int, Query(ge=1, le=MAX_WEEKS, description="어제까지 묶을 주 수")] = DEFAULT_WEEKS,
) -> WeeklyStats:
    try:
        return await weekly_stats(rooms, store, room_id, today=now.astimezone(SEOUL).date(), weeks=weeks)
    except RoomNotFound:
        raise HTTPException(status_code=404, detail="등록되지 않은 방입니다.") from None
