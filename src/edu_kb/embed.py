"""Embeddings locaux via Ollama."""

from __future__ import annotations

import logging
from typing import Protocol

import httpx
import numpy as np

logging.getLogger("httpx").setLevel(logging.WARNING)


class EmbeddingUnavailable(RuntimeError):
    """Ollama injoignable ou modèle absent."""


class Embedder(Protocol):
    model: str

    def embed(self, texts: list[str]) -> np.ndarray: ...


def normalize(vectors: np.ndarray) -> np.ndarray:
    vectors = np.asarray(vectors, dtype=np.float32)
    norms = np.linalg.norm(vectors, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return vectors / norms


class OllamaEmbedder:
    def __init__(self, url: str, model: str, batch_size: int = 16, timeout: float = 120.0):
        self.url = url
        self.model = model
        self.batch_size = batch_size
        self._client = httpx.Client(timeout=timeout)

    def embed(self, texts: list[str]) -> np.ndarray:
        out: list[list[float]] = []
        for i in range(0, len(texts), self.batch_size):
            batch = texts[i : i + self.batch_size]
            try:
                resp = self._client.post(
                    f"{self.url}/api/embed",
                    json={"model": self.model, "input": batch, "truncate": True},
                )
            except httpx.HTTPError as exc:
                raise EmbeddingUnavailable(f"Ollama injoignable sur {self.url} : {exc}") from exc
            if resp.status_code != 200:
                raise EmbeddingUnavailable(
                    f"Ollama a répondu {resp.status_code} pour le modèle {self.model} : {resp.text[:200]}"
                    f" (as-tu lancé `ollama pull {self.model}` ?)"
                )
            out.extend(resp.json()["embeddings"])
        return normalize(np.array(out, dtype=np.float32))
