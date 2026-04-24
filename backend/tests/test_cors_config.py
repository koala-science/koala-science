"""Tests for CORS origin configuration driven by the CORS_ORIGINS env var."""
from httpx import ASGITransport, AsyncClient

from app.core.config import Settings


def test_cors_origins_parses_comma_separated_string():
    s = Settings(CORS_ORIGINS="a,b")
    assert s.CORS_ORIGINS == ["a", "b"]


def test_cors_origins_strips_whitespace_and_empties():
    s = Settings(CORS_ORIGINS="http://localhost:3000, https://koala.science ,")
    assert s.CORS_ORIGINS == ["http://localhost:3000", "https://koala.science"]


def test_cors_origins_accepts_list():
    s = Settings(CORS_ORIGINS=["http://a", "http://b"])
    assert s.CORS_ORIGINS == ["http://a", "http://b"]


def test_cors_origins_default_includes_localhost():
    s = Settings()
    assert "http://localhost:3000" in s.CORS_ORIGINS


async def test_cors_preflight_allows_configured_origin():
    from app.main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        response = await c.options(
            "/api/v1/health",
            headers={
                "Origin": "http://localhost:3000",
                "Access-Control-Request-Method": "GET",
            },
        )
    assert response.headers.get("access-control-allow-origin") == "http://localhost:3000"
