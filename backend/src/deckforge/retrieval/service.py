"""Retrieval service: ingest uploads, then serve passages to the research agent."""

from __future__ import annotations

from pathlib import Path

from deckforge.core.logging import get_logger
from deckforge.database.entities import Asset, AssetChunk
from deckforge.database.repositories import UnitOfWork
from deckforge.models.plan import ResearchSnippet
from deckforge.retrieval.extractors import Extraction, extract_file
from deckforge.retrieval.index import BM25Index, Chunk, chunk_text

log = get_logger(__name__)


class RetrievalService:
    """Indexes uploaded documents and answers queries over one conversation."""

    def __init__(self, uow: UnitOfWork, *, top_k: int = 8) -> None:
        self.uow = uow
        self.top_k = top_k

    # -- ingestion ---------------------------------------------------------- #

    async def ingest(self, asset: Asset, path: Path) -> Extraction:
        """Extract, chunk and persist the contents of ``asset``.

        Extraction failures are recorded on the asset rather than raised: an
        unreadable upload should not fail the whole request, it should just not
        be searchable.
        """
        extraction = extract_file(path)
        chunks: list[Chunk] = []
        position = 0
        for page in extraction.pages:
            page_chunks = chunk_text(
                page.text,
                page=page.page,
                source=asset.filename,
                asset_id=asset.id,
                start_position=position,
            )
            position += len(page_chunks)
            chunks.extend(page_chunks)

        for chunk in chunks:
            self.uow.session.add(
                AssetChunk(
                    asset_id=asset.id,
                    conversation_id=asset.conversation_id,
                    position=chunk.position,
                    page=chunk.page,
                    text=chunk.text,
                    tokens=chunk.tokens,
                )
            )
        asset.kind = extraction.kind
        asset.indexed = bool(chunks)
        asset.excerpt = extraction.excerpt()
        asset.asset_metadata = {
            **asset.asset_metadata,
            **extraction.metadata,
            "chunks": len(chunks),
        }
        await self.uow.flush()
        log.info("retrieval.ingested", asset=asset.id, chunks=len(chunks), kind=extraction.kind)
        return extraction

    # -- query -------------------------------------------------------------- #

    async def build_index(self, conversation_id: str) -> BM25Index:
        """Build a fresh index over everything uploaded to a conversation."""
        rows = await self.uow.chunks.for_conversation(conversation_id)
        index = BM25Index()
        by_asset = {a.id: a for a in await self.uow.assets.list_for_conversation(conversation_id)}
        index.add(
            [
                Chunk(
                    text=row.text,
                    position=row.position,
                    page=row.page,
                    source=by_asset[row.asset_id].filename if row.asset_id in by_asset else "",
                    asset_id=row.asset_id,
                )
                for row in rows
            ]
        )
        return index

    async def has_documents(self, conversation_id: str) -> bool:
        return bool(await self.uow.chunks.for_conversation(conversation_id, limit=1))


class ConversationRetriever:
    """A :class:`~deckforge.agents.research.Retriever` bound to one conversation."""

    def __init__(self, service: RetrievalService, conversation_id: str) -> None:
        self._service = service
        self._conversation_id = conversation_id
        self._index: BM25Index | None = None

    async def search(self, query: str, top_k: int = 8) -> list[ResearchSnippet]:
        """Return the most relevant passages for ``query``."""
        if self._index is None:
            self._index = await self._service.build_index(self._conversation_id)
        if not len(self._index):
            return []
        return [
            ResearchSnippet(
                text=chunk.text,
                source=chunk.source,
                asset_id=chunk.asset_id,
                page=chunk.page,
                score=round(score, 4),
            )
            for chunk, score in self._index.search(query, top_k)
        ]
