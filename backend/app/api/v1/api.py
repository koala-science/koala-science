from fastapi import APIRouter
from app.api.v1.endpoints import auth
from app.api.v1.endpoints import health
from app.api.v1.endpoints import papers
from app.api.v1.endpoints import arguments
from app.api.v1.endpoints import users
from app.api.v1.endpoints import domains
from app.api.v1.endpoints import search
from app.api.v1.endpoints import export
from app.api.v1.endpoints import notifications
from app.api.v1.endpoints import admin
from app.api.v1.endpoints import activity

api_router = APIRouter()

api_router.include_router(health.router, tags=["health"])
api_router.include_router(auth.router, prefix="/auth", tags=["auth"])
api_router.include_router(users.router, prefix="/users", tags=["users"])
api_router.include_router(domains.router, prefix="/domains", tags=["domains"])
api_router.include_router(papers.router, prefix="/papers", tags=["papers"])
api_router.include_router(arguments.router, prefix="/arguments", tags=["arguments"])
api_router.include_router(search.router, prefix="/search", tags=["search"])
api_router.include_router(export.router, prefix="/export", tags=["export"])
api_router.include_router(notifications.router, prefix="/notifications", tags=["notifications"])
api_router.include_router(admin.router, prefix="/admin", tags=["admin"])
api_router.include_router(activity.router, prefix="/activity", tags=["activity"])
