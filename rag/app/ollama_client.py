from __future__ import annotations

import httpx

from .config import get_settings


class OllamaClient:
    def __init__(self) -> None:
        settings = get_settings()
        self.base_url = settings.ollama_base_url.rstrip("/")
        self.embed_model = settings.ollama_embed_model
        self.llm_model = settings.ollama_llm_model
        self._client = httpx.Client(timeout=60)

    def embed(self, inputs: list[str]) -> list[list[float]]:
        response = self._client.post(
            f"{self.base_url}/api/embed",
            json={
                "model": self.embed_model,
                "input": inputs,
            },
        )
        response.raise_for_status()
        data = response.json()
        return data.get("embeddings", [])

    def generate(self, prompt: str) -> str:
        response = self._client.post(
            f"{self.base_url}/api/generate",
            json={
                "model": self.llm_model,
                "prompt": prompt,
                "stream": False,
            },
        )
        response.raise_for_status()
        data = response.json()
        return data.get("response", "").strip()
