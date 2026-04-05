import asyncio
import io
import logging
from functools import partial

from minio import Minio
from minio.error import S3Error

from app.core.config import settings

logger = logging.getLogger(__name__)

_client: Minio | None = None
_bucket_ensured = False


def _get_client() -> Minio:
    global _client
    if _client is None:
        _client = Minio(
            settings.MINIO_ENDPOINT,
            access_key=settings.MINIO_ACCESS_KEY,
            secret_key=settings.MINIO_SECRET_KEY,
            secure=settings.MINIO_SECURE,
        )
    return _client


def _sync_ensure_bucket() -> None:
    global _bucket_ensured
    if _bucket_ensured:
        return
    client = _get_client()
    if not client.bucket_exists(settings.MINIO_BUCKET):
        client.make_bucket(settings.MINIO_BUCKET)
        logger.info("Created MinIO bucket: %s", settings.MINIO_BUCKET)
    _bucket_ensured = True


def _sync_upload(object_key: str, data: bytes, content_type: str) -> None:
    _sync_ensure_bucket()
    client = _get_client()
    client.put_object(
        settings.MINIO_BUCKET,
        object_key,
        io.BytesIO(data),
        length=len(data),
        content_type=content_type,
    )


def _sync_download(object_key: str) -> bytes:
    _sync_ensure_bucket()
    client = _get_client()
    response = client.get_object(settings.MINIO_BUCKET, object_key)
    try:
        return response.read()
    finally:
        response.close()
        response.release_conn()


def _sync_delete(object_key: str) -> None:
    client = _get_client()
    client.remove_object(settings.MINIO_BUCKET, object_key)


async def upload_object(object_key: str, data: bytes, content_type: str) -> None:
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, partial(_sync_upload, object_key, data, content_type))


async def download_object(object_key: str) -> bytes:
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, partial(_sync_download, object_key))


async def delete_object(object_key: str) -> None:
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, partial(_sync_delete, object_key))
