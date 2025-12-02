from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Iterable, Sequence

from qdrant_client import QdrantClient
from qdrant_client.http import models as qmodels

from .config import get_settings


@dataclass
class VectorDocument:
    content: str
    metadata: dict[str, object]


class VectorStore:
    def __init__(self) -> None:
        settings = get_settings()
        self.collection_name = settings.collection_name
        self.client = QdrantClient(
            url=settings.qdrant_url,
            api_key=settings.qdrant_api_key or None,
        )

    def ensure_collection(self, vector_size: int) -> None:
        if self._collection_exists():
            return

        self.client.recreate_collection(
            self.collection_name,
            vectors_config=qmodels.VectorParams(size=vector_size, distance=qmodels.Distance.COSINE),
        )

    def upsert(self, vectors: list[list[float]], documents: Iterable[VectorDocument]) -> None:
        payloads = []
        ids = []
        for doc in documents:
            payloads.append({"text": doc.content, **doc.metadata})
            ids.append(str(uuid.uuid4()))

        if len(vectors) != len(payloads):
            raise ValueError("Anzahl der Vektoren stimmt nicht mit den Dokumenten überein.")

        self.client.upsert(
            collection_name=self.collection_name,
            points=qmodels.Batch(
                ids=ids,
                vectors=vectors,
                payloads=payloads,
            ),
        )

    def search(
        self,
        vector: list[float],
        limit: int,
        roles: Sequence[str],
    ) -> list[dict[str, object]]:
        query_filter = None
        if roles:
            query_filter = qmodels.Filter(
                must=[
                    qmodels.FieldCondition(
                        key="roles",
                        match=qmodels.MatchAny(any=list(roles)),
                    )
                ]
            )

        results = self.client.search(
            collection_name=self.collection_name,
            query_vector=vector,
            limit=limit,
            with_payload=True,
            query_filter=query_filter,
        )
        contexts = []
        for hit in results:
            payload = hit.payload or {}
            contexts.append(
                {
                    "text": payload.get("text", ""),
                    "source": payload.get("source", "unbekannt"),
                    "roles": payload.get("roles", []),
                    "score": hit.score,
                    "metadata": payload,
                }
            )
        return contexts

    def delete_by_metadata(self, **filters: object) -> None:
        """Entfernt Punkte, die alle angegebenen Metadaten-Filter erfüllen."""
        conditions = []
        for key, value in filters.items():
            if value is None:
                continue
            conditions.append(
                qmodels.FieldCondition(
                    key=key,
                    match=qmodels.MatchValue(value=value),
                )
            )

        if not conditions or not self._collection_exists():
            return

        selector = qmodels.FilterSelector(filter=qmodels.Filter(must=conditions))
        self.client.delete(
            collection_name=self.collection_name,
            points_selector=selector,
            wait=True,
        )

    def delete_by_source(self, source: str) -> None:
        """Abwärtskompatible Hülle, um anhand eines Pfades zu löschen."""
        self.delete_by_metadata(source=source)

    def _collection_exists(self) -> bool:
        collections = self.client.get_collections()
        names = {col.name for col in collections.collections or []}
        return self.collection_name in names
