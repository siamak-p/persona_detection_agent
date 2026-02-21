
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


def create_client(
    url: str,
    *,
    api_key: str | None = None,
    timeout: int = 60,
    prefer_grpc: bool = False,
) -> Any:
    try:
        from qdrant_client import QdrantClient

        logger.info("Creating Qdrant client: url=%s, prefer_grpc=%s", url, prefer_grpc)
        return QdrantClient(
            url=url,
            api_key=api_key,
            timeout=timeout,
            prefer_grpc=prefer_grpc,
        )
    except ImportError:
        logger.warning("qdrant-client not installed, using stub client")

        class QdrantClientStub:

            def __init__(self, url: str, **kwargs: Any) -> None:
                self.url = url
                self._kwargs = kwargs

            def __repr__(self) -> str:
                return f"QdrantClientStub(url={self.url!r})"

        return QdrantClientStub(url=url, api_key=api_key, timeout=timeout)


def health_check(client: Any) -> bool:
    try:
        client.get_collections()
        logger.debug("Qdrant health check passed")
        return True
    except Exception as e:
        logger.error("Qdrant health check failed: %s", e)
        return False


def close(client: Any) -> None:
    try:
        if hasattr(client, "close"):
            client.close()
            logger.info("Qdrant client closed")
    except Exception as e:
        logger.warning("Error closing Qdrant client: %s", e)
