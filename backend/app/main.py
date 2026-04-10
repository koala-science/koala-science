from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from app.api.v1.api import api_router
from app.core.config import settings
from app.core.rate_limit import limiter

app = FastAPI(
    title=settings.PROJECT_NAME,
    description="Coalesc[i]ence API — hybrid human/AI scientific peer review platform.",
    version="1.0.0",
    openapi_url=f"{settings.API_V1_STR}/openapi.json",
)

# Rate limiting
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://localhost:3001", "http://localhost:3002", "http://frontend:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router, prefix=settings.API_V1_STR)


# Serve stored files (previews, PDFs, exports) via storage abstraction
CONTENT_TYPES = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".pdf": "application/pdf",
    ".jsonl": "application/jsonl",
    ".json": "application/json",
}


@app.get("/storage/{key:path}")
async def serve_storage_file(key: str):
    from app.core.storage import storage

    data = await storage.read(key)
    if data is None:
        return JSONResponse({"detail": "Not found"}, status_code=404)

    suffix = "." + key.rsplit(".", 1)[-1] if "." in key else ""
    content_type = CONTENT_TYPES.get(suffix, "application/octet-stream")

    return Response(content=data, media_type=content_type, headers={
        "Cache-Control": "public, max-age=86400",
    })
