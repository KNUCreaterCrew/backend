import asyncio
import contextlib
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.clock import Clock, utc_now
from app.connections import RoomConnections
from app.repositories.rooms import RoomRepository, load_rooms
from app.repositories.stats import StatsStore
from app.routers import health, realtime, reports, rooms
from app.services import stats
from app.services.edge import CHECK_INTERVAL_SECONDS, watch_edges
from app.settings import Settings


def create_app(
    rooms_loader: Callable[[], RoomRepository] = load_rooms,
    settings_loader: Callable[[], Settings] = Settings,
    clock: Clock = utc_now,
    edge_check_interval: float = CHECK_INTERVAL_SECONDS,
    stats_check_interval: float = stats.CHECK_INTERVAL_SECONDS,
) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        # 서버가 켜질 때: 설정·시계·방·연결 목록을 준비하고, 장치 연결 감시와 혼잡도 기록을 백그라운드로 띄운다.
        app.state.settings = settings_loader()
        app.state.clock = clock
        app.state.rooms = rooms_loader()
        app.state.connections = RoomConnections()
        app.state.stats = StatsStore(app.state.settings.stats_db_path)
        await asyncio.to_thread(app.state.stats.create_schema)
        tasks = [
            asyncio.create_task(
                watch_edges(app.state.rooms, clock=clock, publish=app.state.connections.broadcast,
                            interval=edge_check_interval)
            ),
            asyncio.create_task(
                stats.record_every_minute(app.state.rooms, app.state.stats, clock=clock,
                                          interval=stats_check_interval)
            ),
        ]
        yield
        # 서버가 꺼질 때: 백그라운드 작업을 멈추고 끝날 때까지 기다린다.
        for task in tasks:
            task.cancel()
        for task in tasks:
            with contextlib.suppress(asyncio.CancelledError):
                await task

    app = FastAPI(title="ZeroFrame Backend", lifespan=lifespan)
    app.include_router(health.router)
    app.include_router(rooms.router)
    app.include_router(reports.router)
    app.include_router(realtime.router)
    return app


app = create_app()
