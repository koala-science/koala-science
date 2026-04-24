"""Tests for /storage/{key:path} path-traversal rejection and happy path."""
import pytest
from httpx import AsyncClient

from app.core.storage import LocalStorage, UnsafeStorageKey


async def test_storage_rejects_dotdot_segment(client: AsyncClient):
    response = await client.get("/storage/../etc/passwd")
    assert response.status_code in (400, 404)
    assert b"root:" not in response.content


async def test_storage_rejects_encoded_traversal(client: AsyncClient):
    response = await client.get("/storage/..%2F..%2Fetc/passwd")
    assert response.status_code == 400
    assert b"root:" not in response.content


async def test_storage_serves_legitimate_file(client: AsyncClient, tmp_path, monkeypatch):
    import app.main as main_module

    legit = LocalStorage(str(tmp_path))
    payload = b"%PDF-1.4 fake pdf bytes"
    await legit.save("pdfs/abs.pdf", payload, content_type="application/pdf")

    monkeypatch.setattr(main_module, "storage", legit, raising=False)
    from app.core import storage as storage_module
    monkeypatch.setattr(storage_module, "storage", legit)

    response = await client.get("/storage/pdfs/abs.pdf")
    assert response.status_code == 200
    assert response.content == payload
    assert response.headers["content-type"] == "application/pdf"


async def test_localstorage_save_rejects_traversal(tmp_path):
    s = LocalStorage(str(tmp_path))
    with pytest.raises(UnsafeStorageKey):
        await s.save("../evil.txt", b"x")


async def test_localstorage_read_rejects_traversal(tmp_path):
    s = LocalStorage(str(tmp_path))
    with pytest.raises(UnsafeStorageKey):
        await s.read("../etc/passwd")


async def test_localstorage_exists_rejects_traversal(tmp_path):
    s = LocalStorage(str(tmp_path))
    with pytest.raises(UnsafeStorageKey):
        await s.exists("../etc/passwd")


async def test_localstorage_rejects_absolute_key(tmp_path):
    s = LocalStorage(str(tmp_path))
    with pytest.raises(UnsafeStorageKey):
        await s.save("/etc/passwd", b"x")


async def test_localstorage_rejects_nested_traversal(tmp_path):
    s = LocalStorage(str(tmp_path))
    with pytest.raises(UnsafeStorageKey):
        await s.save("pdfs/../../escape.txt", b"x")
