"""Sentinel Platform backend — FastAPI app factory.

Run from backend/:  uvicorn app.main:app --host 0.0.0.0 --port 8000
"""
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from .db import Base, engine
from .routers import alerts, cameras, detections, dossier, health, routes, stats, watchlist
from .ws import manager


@asynccontextmanager
async def _lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine)
    yield


def create_app() -> FastAPI:
    app = FastAPI(
        title="Sentinel Platform API",
        description="CCTV integration platform prototype — Gujarat CCTV Hackathon 2026",
        version="0.1.0",
        lifespan=_lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    for router in (
        cameras.router,
        watchlist.router,
        detections.router,
        alerts.router,
        routes.router,
        dossier.router,
        health.router,
        stats.router,
    ):
        app.include_router(router, prefix="/api")

    @app.websocket("/ws/alerts")
    async def ws_alerts(websocket: WebSocket):
        await manager.connect(websocket)
        try:
            while True:
                # No inbound messages expected — drain and ignore anything sent.
                await websocket.receive_text()
        except WebSocketDisconnect:
            pass
        except Exception:
            pass
        finally:
            await manager.disconnect(websocket)

    return app


app = create_app()
