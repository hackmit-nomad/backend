from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.router import api_router


def create_app() -> FastAPI:
    app = FastAPI(title="Nomad API (MVP)")

    allowed_origins = [
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "https://usenomad.app",
        "https://www.usenomad.app"
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
        return {"message": "nomad v3.2.0 mvp"}

    app.include_router(api_router)
    return app


app = create_app()

