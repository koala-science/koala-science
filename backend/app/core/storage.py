"""
Storage abstraction: local filesystem for dev, GCS for production.

Usage:
    from app.core.storage import storage

    # Save a file
    url = await storage.save("previews/abc123.png", file_bytes, content_type="image/png")

    # Get a serving URL (local path or signed GCS URL)
    url = await storage.get_url("previews/abc123.png")

    # Read a file
    data = await storage.read("exports/snapshot.json")
"""
from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from pathlib import Path

from app.core.config import settings


class StorageBackend(ABC):

    @abstractmethod
    async def save(self, key: str, data: bytes, content_type: str = "application/octet-stream") -> str:
        """Save data, return the serving URL/path."""
        ...

    @abstractmethod
    async def read(self, key: str) -> bytes | None:
        """Read file contents. Returns None if not found."""
        ...

    @abstractmethod
    async def get_url(self, key: str) -> str:
        """Get a serving URL for the file."""
        ...

    @abstractmethod
    async def exists(self, key: str) -> bool:
        ...


class LocalStorage(StorageBackend):
    """Filesystem-based storage for local development."""

    def __init__(self, base_dir: str):
        self.base_dir = Path(base_dir)

    async def save(self, key: str, data: bytes, content_type: str = "application/octet-stream") -> str:
        path = self.base_dir / key
        path.parent.mkdir(parents=True, exist_ok=True)

        def _write():
            path.write_bytes(data)

        await asyncio.to_thread(_write)
        return f"/storage/{key}"

    async def read(self, key: str) -> bytes | None:
        path = self.base_dir / key

        def _read():
            return path.read_bytes() if path.exists() else None

        return await asyncio.to_thread(_read)

    async def get_url(self, key: str) -> str:
        return f"/storage/{key}"

    async def exists(self, key: str) -> bool:
        path = self.base_dir / key
        return await asyncio.to_thread(path.exists)


class GCSStorage(StorageBackend):
    """Google Cloud Storage backend for production."""

    def __init__(self, bucket_name: str):
        self.bucket_name = bucket_name
        self._client = None

    @property
    def client(self):
        if self._client is None:
            from google.cloud import storage as gcs
            self._client = gcs.Client()
        return self._client

    @property
    def bucket(self):
        return self.client.bucket(self.bucket_name)

    async def save(self, key: str, data: bytes, content_type: str = "application/octet-stream") -> str:
        def _upload():
            blob = self.bucket.blob(key)
            blob.upload_from_string(data, content_type=content_type)

        await asyncio.to_thread(_upload)
        return await self.get_url(key)

    async def read(self, key: str) -> bytes | None:
        def _download():
            blob = self.bucket.blob(key)
            if not blob.exists():
                return None
            return blob.download_as_bytes()

        return await asyncio.to_thread(_download)

    async def get_url(self, key: str) -> str:
        """Return path routed through our backend."""
        return f"/storage/{key}"

    async def exists(self, key: str) -> bool:
        def _check():
            return self.bucket.blob(key).exists()

        return await asyncio.to_thread(_check)


def _create_storage() -> StorageBackend:
    if settings.STORAGE_BACKEND == "gcs" and settings.GCS_STORAGE_BUCKET:
        return GCSStorage(settings.GCS_STORAGE_BUCKET)
    return LocalStorage(settings.STORAGE_DIR)


storage = _create_storage()
