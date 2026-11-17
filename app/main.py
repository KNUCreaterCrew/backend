from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.repositories.rooms import RoomRepository, load_example_rooms
from app.routers import health, rooms


def create_app(load_rooms: Callable[[], RoomRepository] = load_example_rooms) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.rooms = load_rooms()
        yield

    app = FastAPI(title="ZeroFrame Backend", lifespan=lifespan)
    app.include_router(health.router)
    app.include_router(rooms.router)
    return app


app = create_app()
