from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.clock import Clock, utc_now
from app.repositories.rooms import RoomRepository, load_rooms
from app.routers import health, reports, rooms
from app.settings import Settings


def create_app(
    rooms_loader: Callable[[], RoomRepository] = load_rooms,
    settings_loader: Callable[[], Settings] = Settings,
    clock: Clock = utc_now,
) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.settings = settings_loader()
        app.state.clock = clock
        app.state.rooms = rooms_loader()
        yield

    app = FastAPI(title="ZeroFrame Backend", lifespan=lifespan)
    app.include_router(health.router)
    app.include_router(rooms.router)
    app.include_router(reports.router)
    return app


app = create_app()
