from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .routers.auth_users import router as auth_users_router
from .routers.communities_feed import router as communities_feed_router
from .routers.courses_planner import router as courses_planner_router
from .routers.messages_misc import router as messages_misc_router


def create_app() -> FastAPI:
    app = FastAPI(title="Nomad API (MVP)", version="1.0.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(auth_users_router)
    app.include_router(courses_planner_router)
    app.include_router(communities_feed_router)
    app.include_router(messages_misc_router)
    return app


app = create_app()
