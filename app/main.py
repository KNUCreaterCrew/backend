from fastapi import FastAPI

from app.routers import health

app = FastAPI(title="ZeroFrame Backend")
app.include_router(health.router)
