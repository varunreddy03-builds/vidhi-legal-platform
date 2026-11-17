"""Stored uploads (GridFS), encrypted at rest when DATA_ENCRYPTION_KEY is set. Every read and write of an uploaded file goes
through here, so a new route cannot forget to encrypt or to decrypt."""

from motor.motor_asyncio import AsyncIOMotorGridFSBucket

from lib import crypto
from lib.db import db

_AAD = b"vidhi-file"


def _fs() -> AsyncIOMotorGridFSBucket:
    return AsyncIOMotorGridFSBucket(db)


async def put(filename: str, data: bytes, metadata: dict) -> object:
    meta = {**metadata, "encrypted": crypto.enabled()}
    return await _fs().upload_from_stream(filename, crypto.encrypt(data, _AAD), metadata=meta)


async def read(file_id: object) -> bytes:
    stream = await _fs().open_download_stream(file_id)
    return crypto.decrypt(await stream.read(), _AAD)


async def delete(file_id: object) -> None:
    await _fs().delete(file_id)