from __future__ import annotations

from pathlib import Path

try:  # Tokenizer ist optional; fällt auf Whitespace-Splits zurück
    import tiktoken
except ImportError:  # pragma: no cover - optional dependency
    tiktoken = None


def read_text_file(path: Path) -> str:
    if not path.exists():
        raise FileNotFoundError(f"Datei {path} wurde nicht gefunden.")
    return path.read_text(encoding="utf-8")


def chunk_text(
    text: str,
    chunk_size: int,
    chunk_overlap: int,
    tokenizer_name: str | None = None,
) -> list[str]:
    """Sliding-Window-Splitter auf Token-Basis (fällt auf Wörter zurück, wenn kein Tokenizer)."""
    if chunk_size <= 0:
        return []

    encoder = _get_encoder(tokenizer_name)
    tokens = _encode(text, encoder)
    if not tokens:
        return []

    chunks = []
    start = 0
    while start < len(tokens):
        end = start + chunk_size
        token_slice = tokens[start:end]
        chunk = _decode(token_slice, encoder).strip()
        if chunk:
            chunks.append(chunk)
        if end >= len(tokens):
            break
        start = max(0, end - chunk_overlap)
    return chunks


def _get_encoder(name: str | None):
    if not tiktoken:
        return None
    target = name or "cl100k_base"
    try:
        return tiktoken.get_encoding(target)
    except Exception:  # pragma: no cover - nur bei ungültigem Namen
        return None


def _encode(text: str, encoder) -> list:
    if encoder:
        return encoder.encode(text)
    return text.split()


def _decode(tokens: list, encoder) -> str:
    if encoder:
        return encoder.decode(tokens)
    return " ".join(tokens)
