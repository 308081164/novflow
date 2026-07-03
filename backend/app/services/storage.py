from __future__ import annotations

import io
import logging
from pathlib import Path

from minio import Minio
from minio.error import S3Error

from app.config import DATA_DIR, settings

logger = logging.getLogger(__name__)


class StorageService:
    def __init__(self) -> None:
        self._client: Minio | None = None

    @property
    def enabled(self) -> bool:
        return settings.use_minio

    @property
    def _local_media_root(self) -> Path:
        root = DATA_DIR / "media"
        root.mkdir(parents=True, exist_ok=True)
        return root

    def _local_path(self, object_key: str) -> Path:
        key = object_key.lstrip("/").replace("\\", "/")
        if not key or ".." in key.split("/"):
            raise ValueError(f"Invalid object key: {object_key}")
        path = (self._local_media_root / key).resolve()
        root = self._local_media_root.resolve()
        if path != root and root not in path.parents:
            raise ValueError(f"Invalid object key: {object_key}")
        return path

    def _get_client(self) -> Minio:
        if self._client is None:
            self._client = Minio(
                settings.minio_endpoint,
                access_key=settings.minio_access_key,
                secret_key=settings.minio_secret_key,
                secure=settings.minio_secure,
            )
        return self._client

    @staticmethod
    def object_key(book_id: int, chapter_no: int) -> str:
        return f"{book_id}/{chapter_no}.md"

    def ensure_bucket(self) -> None:
        if not self.enabled:
            self._local_media_root.mkdir(parents=True, exist_ok=True)
            return
        try:
            client = self._get_client()
            bucket = settings.minio_bucket
            if not client.bucket_exists(bucket):
                client.make_bucket(bucket)
                logger.info("Created MinIO bucket: %s", bucket)
            else:
                logger.info("MinIO bucket ready: %s", bucket)
        except Exception as exc:
            logger.warning("MinIO not ready at startup (will retry on use): %s", exc)

    def put_chapter(self, book_id: int, chapter_no: int, content: str) -> None:
        if not self.enabled:
            return
        client = self._get_client()
        data = content.encode("utf-8")
        client.put_object(
            settings.minio_bucket,
            self.object_key(book_id, chapter_no),
            io.BytesIO(data),
            length=len(data),
            content_type="text/markdown; charset=utf-8",
        )

    def get_chapter(self, book_id: int, chapter_no: int) -> str | None:
        if not self.enabled:
            return None
        client = self._get_client()
        key = self.object_key(book_id, chapter_no)
        try:
            response = client.get_object(settings.minio_bucket, key)
            try:
                return response.read().decode("utf-8")
            finally:
                response.close()
                response.release_conn()
        except S3Error as exc:
            if exc.code in ("NoSuchKey", "NoSuchObject"):
                return None
            raise

    def delete_chapter(self, book_id: int, chapter_no: int) -> None:
        if not self.enabled:
            return
        client = self._get_client()
        try:
            client.remove_object(settings.minio_bucket, self.object_key(book_id, chapter_no))
        except S3Error:
            pass

    def put_bytes(self, object_key: str, data: bytes, content_type: str = "application/octet-stream") -> None:
        if not self.enabled:
            path = self._local_path(object_key)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
            return
        client = self._get_client()
        client.put_object(
            settings.minio_bucket,
            object_key,
            io.BytesIO(data),
            length=len(data),
            content_type=content_type,
        )

    def get_bytes(self, object_key: str) -> bytes | None:
        if not object_key:
            return None
        if not self.enabled:
            path = self._local_path(object_key)
            if not path.is_file():
                return None
            return path.read_bytes()
        client = self._get_client()
        try:
            response = client.get_object(settings.minio_bucket, object_key)
            try:
                return response.read()
            finally:
                response.close()
                response.release_conn()
        except S3Error as exc:
            if exc.code in ("NoSuchKey", "NoSuchObject"):
                return None
            raise

    def delete_object(self, object_key: str) -> None:
        if not object_key:
            return
        if not self.enabled:
            try:
                path = self._local_path(object_key)
                if path.is_file():
                    path.unlink()
            except (ValueError, OSError):
                pass
            return
        client = self._get_client()
        try:
            client.remove_object(settings.minio_bucket, object_key)
        except S3Error:
            pass

    def delete_prefix(self, prefix: str) -> None:
        if not prefix:
            return
        if not self.enabled:
            import shutil

            clean = prefix.lstrip("/").replace("\\", "/").rstrip("/")
            if not clean or ".." in clean.split("/"):
                return
            root = self._local_media_root.resolve()
            target = (root / clean).resolve()
            if target != root and root not in target.parents:
                return
            if target.is_dir():
                shutil.rmtree(target, ignore_errors=True)
            elif target.is_file():
                target.unlink(missing_ok=True)
            else:
                prefix_slash = f"{clean}/"
                for path in root.rglob("*"):
                    rel = path.relative_to(root).as_posix()
                    if rel == clean or rel.startswith(prefix_slash):
                        if path.is_file():
                            path.unlink(missing_ok=True)
                remaining = root / clean
                if remaining.is_dir():
                    shutil.rmtree(remaining, ignore_errors=True)
            return
        client = self._get_client()
        bucket = settings.minio_bucket
        try:
            for obj in client.list_objects(bucket, prefix=prefix, recursive=True):
                try:
                    client.remove_object(bucket, obj.object_name)
                except S3Error:
                    pass
        except S3Error:
            pass


storage = StorageService()
