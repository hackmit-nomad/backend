from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.router import api_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    import asyncio

    from app.realtime.bridge import start_realtime_bridge

    start_realtime_bridge(asyncio.get_running_loop())
    yield


def create_app() -> FastAPI:
    app = FastAPI(title="Nomad API (MVP)", lifespan=lifespan)

    allowed_origins = [
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ]

    app.add_middleware(
        CORSMiddleware,
        allow_origins=allowed_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/")
    async def root():
        return {"message": "nomad v3.1.0 mvp"}

    app.include_router(api_router)
    return app


app = create_app()

