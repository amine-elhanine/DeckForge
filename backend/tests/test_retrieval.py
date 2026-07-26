"""Document extraction, chunking and BM25 retrieval."""

from __future__ import annotations

import csv

import pytest

from deckforge.core.errors import UnsupportedFileError
from deckforge.retrieval.extractors import extract_file, supported_extensions
from deckforge.retrieval.index import BM25Index, Chunk, chunk_text

SAMPLE = """\
# Reinforcement learning notes

The pilot reduced average handling time by 23% over eight weeks.

The reward model was trained on 4,200 ranked preference pairs collected from
twelve annotators over a month.

The main risk we identified was reward hacking in the escalation path, where the
policy learned to close tickets rather than resolve them.
"""


def test_supported_extensions_cover_the_documented_set() -> None:
    assert {"pdf", "docx", "pptx", "md", "txt", "csv", "xlsx", "png"} <= set(supported_extensions())


def test_markdown_extraction(tmp_path) -> None:
    path = tmp_path / "notes.md"
    path.write_text(SAMPLE, encoding="utf-8")
    extraction = extract_file(path)
    assert "reward hacking" in extraction.text
    assert extraction.excerpt(80).endswith("…")


def test_csv_extraction(tmp_path) -> None:
    path = tmp_path / "data.csv"
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerows([["algo", "steps"], ["PPO", "6"], ["SAC", "4"]])
    extraction = extract_file(path)
    assert "PPO | 6" in extraction.text
    assert extraction.kind == "data"


def test_pptx_round_trip(tmp_path, deck, themes, layouts, renderer) -> None:
    """A deck we export must be readable back in as source material."""
    from deckforge.exporters.base import EXPORTERS, ExportContext

    context = ExportContext(theme=themes.for_deck(deck), layouts=layouts, renderer=renderer)
    path = tmp_path / "deck.pptx"
    path.write_bytes(EXPORTERS.get("pptx").export(deck, context).content)

    extraction = extract_file(path)
    assert extraction.kind == "presentation"
    assert len(extraction.pages) == len(deck.slides)
    assert "Reinforcement Learning" in extraction.text


def test_unsupported_extension_raises(tmp_path) -> None:
    path = tmp_path / "thing.exe"
    path.write_bytes(b"\x00")
    with pytest.raises(UnsupportedFileError):
        extract_file(path)


def test_chunking_is_paragraph_aligned() -> None:
    chunks = chunk_text(SAMPLE, target_chars=120, source="notes.md", asset_id="ast_1")
    assert len(chunks) > 1
    assert all(c.source == "notes.md" for c in chunks)
    assert all(c.text.strip() == c.text for c in chunks)
    assert [c.position for c in chunks] == list(range(len(chunks)))


def test_chunking_handles_a_single_huge_paragraph() -> None:
    blob = " ".join(f"Sentence number {i} about reinforcement learning." for i in range(120))
    chunks = chunk_text(blob, target_chars=300)
    assert len(chunks) > 3
    assert max(len(c.text) for c in chunks) < 900


def test_chunking_empty_text() -> None:
    assert chunk_text("   \n  ") == []


def test_bm25_ranks_the_relevant_chunk_first() -> None:
    index = BM25Index()
    index.add(
        [
            Chunk(
                text="The pilot reduced average handling time by 23% over eight weeks.", position=0
            ),
            Chunk(
                text="The reward model was trained on 4,200 ranked preference pairs.", position=1
            ),
            Chunk(text="Lunch options in the office cafeteria on Tuesdays.", position=2),
        ]
    )
    results = index.search("how was the reward model trained", top_k=2)
    assert results
    assert "reward model" in results[0][0].text
    assert results[0][1] > 0


def test_bm25_empty_query_and_index() -> None:
    assert BM25Index().search("anything") == []
    index = BM25Index()
    index.add([Chunk(text="content here")])
    assert index.search("   ") == []
