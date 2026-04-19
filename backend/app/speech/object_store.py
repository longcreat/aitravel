"""语音对象存储。"""

from __future__ import annotations

import asyncio
import os
import shutil
from pathlib import Path
from typing import AsyncIterator, Protocol


class SpeechObjectStore(Protocol):
    async def put_file(self, source_path: Path, object_key: str, mime_type: str) -> None:
        ...

    async def iter_file(self, object_key: str, chunk_size: int = 65536) -> AsyncIterator[bytes]:
        ...


class LocalSpeechObjectStore:
    """本地磁盘对象存储。"""

    def __init__(self, root: Path) -> None:
        self._root = root
        self._root.mkdir(parents=True, exist_ok=True)

    def _resolve(self, object_key: str) -> Path:
        target = self._root / object_key
        target.parent.mkdir(parents=True, exist_ok=True)
        return target

    async def put_file(self, source_path: Path, object_key: str, mime_type: str) -> None:
        del mime_type
        target = self._resolve(object_key)
        await asyncio.to_thread(shutil.copyfile, source_path, target)

    async def iter_file(self, object_key: str, chunk_size: int = 65536) -> AsyncIterator[bytes]:
        target = self._resolve(object_key)
        file_handle = target.open("rb")
        try:
            while True:
                chunk = await asyncio.to_thread(file_handle.read, chunk_size)
                if not chunk:
                    break
                yield chunk
        finally:
            file_handle.close()


class R2SpeechObjectStore:
    """Cloudflare R2 对象存储。"""

    def __init__(
        self,
        *,
        account_id: str,
        access_key_id: str,
        secret_access_key: str,
        bucket: str,
    ) -> None:
        import boto3

        self._bucket = bucket
        self._client = boto3.client(
            service_name="s3",
            endpoint_url=f"https://{account_id}.r2.cloudflarestorage.com",
            aws_access_key_id=access_key_id,
            aws_secret_access_key=secret_access_key,
            region_name="auto",
        )

    async def put_file(self, source_path: Path, object_key: str, mime_type: str) -> None:
        await asyncio.to_thread(
            self._client.upload_file,
            str(source_path),
            self._bucket,
            object_key,
            ExtraArgs={"ContentType": mime_type},
        )

    async def iter_file(self, object_key: str, chunk_size: int = 65536) -> AsyncIterator[bytes]:
        response = await asyncio.to_thread(
            self._client.get_object,
            Bucket=self._bucket,
            Key=object_key,
        )
        body = response["Body"]
        try:
            while True:
                chunk = await asyncio.to_thread(body.read, chunk_size)
                if not chunk:
                    break
                yield chunk
        finally:
            await asyncio.to_thread(body.close)


def build_speech_object_store(root: Path) -> SpeechObjectStore:
    """构建语音对象存储，优先使用 R2。"""

    account_id = os.getenv("R2_ACCOUNT_ID", "").strip()
    access_key_id = os.getenv("R2_ACCESS_KEY_ID", "").strip()
    secret_access_key = os.getenv("R2_SECRET_ACCESS_KEY", "").strip()
    bucket = os.getenv("R2_BUCKET", "").strip()

    if all([account_id, access_key_id, secret_access_key, bucket]):
        return R2SpeechObjectStore(
            account_id=account_id,
            access_key_id=access_key_id,
            secret_access_key=secret_access_key,
            bucket=bucket,
        )

    return LocalSpeechObjectStore(root)
