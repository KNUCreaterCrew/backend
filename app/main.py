from fastapi import FastAPI

from app.routers import health, rooms

app = FastAPI(title="ZeroFrame Backend")
app.include_router(health.router)
app.include_router(rooms.router)
