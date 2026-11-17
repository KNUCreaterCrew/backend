from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.repositories.rooms import RoomRepository, load_rooms
from app.routers import health, rooms


def create_app(rooms_loader: Callable[[], RoomRepository] = load_rooms) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.rooms = rooms_loader()
        yield

    app = FastAPI(title="ZeroFrame Backend", lifespan=lifespan)
    app.include_router(health.router)
    app.include_router(rooms.router)
    return app


app = create_app()
