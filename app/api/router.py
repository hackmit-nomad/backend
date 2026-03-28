from fastapi import APIRouter

from app.api.routes import (
    calendar,
    communities,
    courses,
    feed,
    ingest,
    notifications,
    onboarding,
    planner,
    search,
    users,
)
from app.api.ws.messages_ws import router as messages_ws_router

api_router = APIRouter()

api_router.include_router(users.router)
api_router.include_router(ingest.router)
api_router.include_router(courses.router)
api_router.include_router(communities.router)
api_router.include_router(feed.router)
api_router.include_router(messages_ws_router)
api_router.include_router(calendar.router)
api_router.include_router(notifications.router)
api_router.include_router(onboarding.router)
api_router.include_router(planner.router)
api_router.include_router(search.router)

