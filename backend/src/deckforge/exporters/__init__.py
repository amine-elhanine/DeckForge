"""Exporters: deck JSON to PPTX, PDF, Markdown, HTML, Reveal.js and Marp."""

from deckforge.exporters.base import (
    EXPORTERS,
    ExportContext,
    Exporter,
    ExportResult,
    exporter_catalog,
    register_exporter,
)
from deckforge.exporters.pdf_exporter import PdfExporter
from deckforge.exporters.pptx_exporter import PptxExporter
from deckforge.exporters.text_formats import (
    HtmlExporter,
    MarkdownExporter,
    MarpExporter,
    RevealJsExporter,
)


def register_builtin_exporters() -> None:
    """Register the shipped exporters. Idempotent, so plugins may call it too."""
    for exporter in (
        PptxExporter(),
        PdfExporter(),
        HtmlExporter(),
        MarkdownExporter(),
        RevealJsExporter(),
        MarpExporter(),
    ):
        register_exporter(exporter, override=True)


register_builtin_exporters()

__all__ = [
    "EXPORTERS",
    "ExportContext",
    "ExportResult",
    "Exporter",
    "HtmlExporter",
    "MarkdownExporter",
    "MarpExporter",
    "PdfExporter",
    "PptxExporter",
    "RevealJsExporter",
    "exporter_catalog",
    "register_builtin_exporters",
    "register_exporter",
]
