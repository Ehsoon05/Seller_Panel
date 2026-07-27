from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from . import models  # noqa: F401
from .admin_routes import router as admin_router
from .config import settings
from .database import initialize_database
from .seller_routes import router as seller_router


@asynccontextmanager
async def lifespan(_app: FastAPI):
    await initialize_database()
    yield


app = FastAPI(title="Phantom Hubs Seller Panel", version="1.0.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(seller_router)
app.include_router(admin_router)


@app.get("/healthz")
async def healthz():
    return {"status": "ok"}


dist = Path(__file__).resolve().parents[1] / "frontend" / "dist"
assets = dist / "assets"
if assets.exists():
    app.mount("/assets", StaticFiles(directory=assets), name="assets")


@app.get("/{path:path}")
async def frontend(path: str):
    candidate = dist / path
    if path and candidate.is_file():
        return FileResponse(candidate)
    index = dist / "index.html"
    if index.exists():
        return FileResponse(index)
    return {"detail": "Frontend build is not installed"}

