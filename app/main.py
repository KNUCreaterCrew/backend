import asyncio
import contextlib
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.clock import Clock, utc_now
from app.connections import RoomConnections
from app.repositories.rooms import RoomRepository, load_rooms
from app.routers import health, realtime, reports, rooms
from app.services.edge import CHECK_INTERVAL_SECONDS, watch_edges
from app.settings import Settings


def create_app(
    rooms_loader: Callable[[], RoomRepository] = load_rooms,
    settings_loader: Callable[[], Settings] = Settings,
    clock: Clock = utc_now,
    edge_check_interval: float = CHECK_INTERVAL_SECONDS,
) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        # 서버가 켜질 때: 설정·시계·방·연결 목록을 준비하고, 장치 연결 감시를 백그라운드로 띄운다.
        app.state.settings = settings_loader()
        app.state.clock = clock
        app.state.rooms = rooms_loader()
        app.state.connections = RoomConnections()
        watcher = asyncio.create_task(
            watch_edges(app.state.rooms, clock=clock, publish=app.state.connections.broadcast,
                        interval=edge_check_interval)
        )
        yield
        # 서버가 꺼질 때: 감시 작업을 멈추고 끝날 때까지 기다린다.
        watcher.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await watcher

    app = FastAPI(title="ZeroFrame Backend", lifespan=lifespan)
    app.include_router(health.router)
    app.include_router(rooms.router)
    app.include_router(reports.router)
    app.include_router(realtime.router)
    return app


app = create_app()
