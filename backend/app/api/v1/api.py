from fastapi import APIRouter
from app.api.v1.endpoints import auth
from app.api.v1.endpoints import health
from app.api.v1.endpoints import papers
from app.api.v1.endpoints import comments
from app.api.v1.endpoints import verdicts
from app.api.v1.endpoints import votes
from app.api.v1.endpoints import users
from app.api.v1.endpoints import domains
from app.api.v1.endpoints import reputation
from app.api.v1.endpoints import search
from app.api.v1.endpoints import export
from app.api.v1.endpoints import leaderboard
from app.api.v1.endpoints import notifications
from app.api.v1.endpoints import admin

api_router = APIRouter()

api_router.include_router(health.router, tags=["health"])
api_router.include_router(auth.router, prefix="/auth", tags=["auth"])
api_router.include_router(users.router, prefix="/users", tags=["users"])
api_router.include_router(domains.router, prefix="/domains", tags=["domains"])
api_router.include_router(papers.router, prefix="/papers", tags=["papers"])
api_router.include_router(comments.router, prefix="/comments", tags=["comments"])
api_router.include_router(verdicts.router, prefix="/verdicts", tags=["verdicts"])
api_router.include_router(votes.router, prefix="/votes", tags=["votes"])
api_router.include_router(reputation.router, prefix="/reputation", tags=["reputation"])
api_router.include_router(search.router, prefix="/search", tags=["search"])
api_router.include_router(export.router, prefix="/export", tags=["export"])
api_router.include_router(leaderboard.router, prefix="/leaderboard", tags=["leaderboard"])
api_router.include_router(notifications.router, prefix="/notifications", tags=["notifications"])
api_router.include_router(admin.router, prefix="/admin", tags=["admin"])
