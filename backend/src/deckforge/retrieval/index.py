"""Chunking and BM25 retrieval.

Deliberately dependency-free: no embedding model, no vector database, no
download on first run. BM25 over a few uploaded documents is fast, explainable
and good enough for "pull the relevant paragraphs into the deck". Swapping in
embeddings later means implementing the same ``search`` signature.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass, field

from deckforge.utils.text import estimate_tokens, tokenize

_PARAGRAPH_RE = re.compile(r"\n\s*\n")


@dataclass(slots=True)
class Chunk:
    """A retrievable passage."""

    text: str
    position: int = 0
    page: int | None = None
    source: str = ""
    asset_id: str | None = None

    @property
    def tokens(self) -> int:
        return estimate_tokens(self.text)


def chunk_text(
    text: str,
    *,
    target_chars: int = 1200,
    overlap_chars: int = 150,
    page: int | None = None,
    source: str = "",
    asset_id: str | None = None,
    start_position: int = 0,
) -> list[Chunk]:
    """Split ``text`` into overlapping, paragraph-aligned chunks.

    Paragraph alignment matters: a chunk that starts mid-sentence retrieves badly
    and reads worse when quoted onto a slide.
    """
    body = text.strip()
    if not body:
        return []

    paragraphs = [p.strip() for p in _PARAGRAPH_RE.split(body) if p.strip()]
    chunks: list[Chunk] = []
    buffer = ""
    position = start_position

    def flush() -> None:
        nonlocal buffer, position
        if buffer.strip():
            chunks.append(
                Chunk(
                    text=buffer.strip(),
                    position=position,
                    page=page,
                    source=source,
                    asset_id=asset_id,
                )
            )
            position += 1

    for paragraph in paragraphs:
        if len(paragraph) > target_chars * 1.6:
            # A single huge paragraph: hard-split on sentence boundaries.
            for sentence in re.split(r"(?<=[.!?])\s+", paragraph):
                if len(buffer) + len(sentence) > target_chars:
                    flush()
                    buffer = buffer[-overlap_chars:] if overlap_chars else ""
                buffer = f"{buffer} {sentence}".strip()
            continue
        if len(buffer) + len(paragraph) > target_chars and buffer:
            flush()
            buffer = buffer[-overlap_chars:] if overlap_chars else ""
        buffer = f"{buffer}\n\n{paragraph}".strip()

    flush()
    return chunks


@dataclass(slots=True)
class BM25Index:
    """An in-memory BM25 index over a conversation's chunks.

    Small enough to rebuild on demand (thousands of chunks build in milliseconds),
    so there is no persistence or invalidation to get wrong.
    """

    k1: float = 1.5
    b: float = 0.75
    chunks: list[Chunk] = field(default_factory=list)
    _terms: list[Counter[str]] = field(default_factory=list)
    _lengths: list[int] = field(default_factory=list)
    _document_frequency: Counter[str] = field(default_factory=Counter)
    _average_length: float = 0.0

    def add(self, chunks: list[Chunk]) -> None:
        """Index a batch of chunks."""
        for chunk in chunks:
            terms = Counter(tokenize(chunk.text))
            if not terms:
                continue
            self.chunks.append(chunk)
            self._terms.append(terms)
            self._lengths.append(sum(terms.values()))
            self._document_frequency.update(terms.keys())
        total = sum(self._lengths)
        self._average_length = total / len(self._lengths) if self._lengths else 0.0

    def search(self, query: str, top_k: int = 8) -> list[tuple[Chunk, float]]:
        """Return the ``top_k`` chunks scored against ``query``."""
        query_terms = tokenize(query)
        if not query_terms or not self.chunks:
            return []

        count = len(self.chunks)
        scores: list[float] = [0.0] * count
        for term in set(query_terms):
            document_frequency = self._document_frequency.get(term, 0)
            if not document_frequency:
                continue
            idf = math.log(1 + (count - document_frequency + 0.5) / (document_frequency + 0.5))
            for i, terms in enumerate(self._terms):
                frequency = terms.get(term, 0)
                if not frequency:
                    continue
                length_norm = (
                    1 - self.b + self.b * (self._lengths[i] / (self._average_length or 1.0))
                )
                scores[i] += idf * (frequency * (self.k1 + 1)) / (frequency + self.k1 * length_norm)

        ranked = sorted(
            ((self.chunks[i], score) for i, score in enumerate(scores) if score > 0),
            key=lambda pair: -pair[1],
        )
        return ranked[:top_k]

    def __len__(self) -> int:
        return len(self.chunks)
