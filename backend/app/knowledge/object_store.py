from typing import Protocol

from backend.app.core.settings import S3Settings


class KnowledgeObjectStore(Protocol):
    async def put_text(
        self,
        key: str,
        text: str,
        *,
        content_type: str = "text/plain; charset=utf-8",
    ) -> str:
        raise NotImplementedError


class InMemoryKnowledgeObjectStore:
    def __init__(self, *, bucket: str = "aegis-flow") -> None:
        self.bucket = bucket
        self.objects: dict[str, str] = {}

    async def put_text(
        self,
        key: str,
        text: str,
        *,
        content_type: str = "text/plain; charset=utf-8",
    ) -> str:
        self.objects[key] = text
        return f"s3://{self.bucket}/{key}"


class S3KnowledgeObjectStore:
    def __init__(self, settings: S3Settings) -> None:
        self._settings = settings

    async def put_text(
        self,
        key: str,
        text: str,
        *,
        content_type: str = "text/plain; charset=utf-8",
    ) -> str:
        import aioboto3  # type: ignore[import-untyped]

        session = aioboto3.Session()
        async with session.client(
            "s3",
            endpoint_url=self._settings.endpoint,
            region_name=self._settings.region,
            aws_access_key_id=self._settings.access_key.get_secret_value(),
            aws_secret_access_key=self._settings.secret_key.get_secret_value(),
        ) as client:
            await client.put_object(
                Bucket=self._settings.bucket,
                Key=key,
                Body=text.encode("utf-8"),
                ContentType=content_type,
            )
        return f"s3://{self._settings.bucket}/{key}"


def build_knowledge_object_store(settings: S3Settings) -> KnowledgeObjectStore:
    if settings.enabled:
        return S3KnowledgeObjectStore(settings)
    return InMemoryKnowledgeObjectStore(bucket=settings.bucket)
