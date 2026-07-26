"""Local retrieval over uploaded documents (extract -> chunk -> BM25)."""

from deckforge.retrieval.extractors import (
    EXTRACTORS,
    Extraction,
    Extractor,
    extract_file,
    register_extractor,
    supported_extensions,
)
from deckforge.retrieval.index import BM25Index, Chunk, chunk_text
from deckforge.retrieval.service import ConversationRetriever, RetrievalService

__all__ = [
    "EXTRACTORS",
    "BM25Index",
    "Chunk",
    "ConversationRetriever",
    "Extraction",
    "Extractor",
    "RetrievalService",
    "chunk_text",
    "extract_file",
    "register_extractor",
    "supported_extensions",
]
