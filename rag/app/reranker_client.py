from __future__ import annotations

import httpx

from .config import get_settings


class RerankerClient:
    def __init__(self) -> None:
        settings = get_settings()
        self.base_url = settings.reranker_url.rstrip("/") if settings.reranker_url else None
        self.top_k = settings.reranker_top_k
        self._client = httpx.Client(timeout=30)

    @property
    def enabled(self) -> bool:
        return self.base_url is not None

    def rerank(
        self,
        query: str,
        documents: list[dict],
        top_k: int | None = None,
    ) -> list[dict]:
        """Re-rankt Dokumente basierend auf ihrer Relevanz zur Query.

        Args:
            query: Die Suchanfrage
            documents: Liste von Dokumenten mit 'text' und anderen Metadaten
            top_k: Anzahl der zurückzugebenden Top-Dokumente

        Returns:
            Die top_k relevantesten Dokumente, sortiert nach Relevanz
        """
        if not self.enabled or not documents:
            return documents

        top_k = top_k or self.top_k
        texts = [doc.get("text", "") for doc in documents]

        response = self._client.post(
            f"{self.base_url}/rerank",
            json={
                "query": query,
                "texts": texts,
                "return_text": False,
            },
        )
        response.raise_for_status()
        results = response.json()

        scored_docs = []
        for item in results:
            idx = item["index"]
            score = item["score"]
            doc = documents[idx].copy()
            doc["rerank_score"] = score
            scored_docs.append(doc)

        scored_docs.sort(key=lambda x: x["rerank_score"], reverse=True)
        return scored_docs[:top_k]
