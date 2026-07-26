"""Command line interface.

python -m deckforge.cli serve
python -m deckforge.cli render-sample --theme neon --out sample.html
python -m deckforge.cli export --format pptx --theme corporate --out deck.pptx
python -m deckforge.cli doctor
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

from deckforge import __version__
from deckforge.config import get_settings
from deckforge.container import Container
from deckforge.exporters.base import EXPORTERS, ExportContext, exporter_catalog
from deckforge.samples import sample_deck


def _container() -> Container:
    return Container.create()


def cmd_serve(args: argparse.Namespace) -> int:
    """Run the API server."""
    import uvicorn

    uvicorn.run(
        "deckforge.main:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
        log_level=get_settings().log_level.lower(),
    )
    return 0


def cmd_mcp(args: argparse.Namespace) -> int:
    """Serve DeckForge to other agents over MCP (stdio).

    Nothing in this path may print: stdout carries the protocol.
    """
    try:
        from deckforge.mcp.server import main as mcp_main
    except ImportError:
        print(
            "The MCP server needs its SDK: pip install 'deckforge[mcp]'",
            file=sys.stderr,
        )
        return 2
    return mcp_main([])


def cmd_render_sample(args: argparse.Namespace) -> int:
    """Render the built-in sample deck as HTML."""
    container = _container()
    deck = sample_deck(args.theme)
    theme = container.themes.for_deck(deck)
    if args.contact_sheet:
        fragment = container.renderer.render_deck_fragment(deck, theme)
        css = container.renderer.stylesheet(theme)
        html = (
            f"<!doctype html><html><head><meta charset='utf-8'><title>{deck.title}</title>"
            f"<style>{css}.df-deck{{display:grid;grid-template-columns:repeat(3,1fr);"
            f"gap:10px;max-width:none}}.df-notes{{display:none}}</style></head>"
            f"<body class='df-body'><main class='df-deck'>{fragment}</main></body></html>"
        )
    else:
        html = container.renderer.render_document(deck, theme, include_notes=args.notes)
    Path(args.out).write_text(html, encoding="utf-8")
    print(f"wrote {args.out} ({len(deck.slides)} slides, theme '{theme.name}')")
    return 0


def cmd_export(args: argparse.Namespace) -> int:
    """Export the sample deck (or a deck JSON file) in any format."""
    container = _container()
    if args.deck:
        from deckforge.models.deck import Presentation

        deck = Presentation.model_validate_json(Path(args.deck).read_text(encoding="utf-8"))
        if args.theme:
            deck.theme = args.theme
    else:
        deck = sample_deck(args.theme or "minimal")

    exporter = EXPORTERS.try_get(args.format)
    if exporter is None:
        print(f"unknown format '{args.format}'. available: {EXPORTERS.names()}", file=sys.stderr)
        return 2
    context = ExportContext(
        theme=container.themes.for_deck(deck),
        layouts=container.layouts,
        renderer=container.renderer,
        assets_dir=container.settings.assets_dir,
    )
    result = exporter.export(deck, context)
    target = Path(args.out or result.filename)
    target.write_bytes(result.content)
    print(f"wrote {target} ({result.size:,} bytes)")
    return 0


def cmd_catalog(args: argparse.Namespace) -> int:
    """Print what this installation supports."""
    container = _container()
    print(f"DeckForge {__version__}\n")
    print(f"Themes ({len(container.themes.names())}):")
    for info in container.themes.catalog():
        print(f"  {info['name']:<16} {info['mode']:<6} {info['description']}")
    print(f"\nLayouts ({len(container.layouts.names())}):")
    for info in container.layouts.catalog():
        print(f"  {info['name']:<18} {info['description']}")
    print("\nExport formats:")
    for info in exporter_catalog():
        print(f"  {info['name']:<10} .{info['extension']:<5} {info['description']}")
    print("\nProviders:")
    for info in container.providers.describe():
        mark = "✓" if info["configured"] else "·"
        print(f"  {mark} {info['name']:<12} {info['kind']:<6} {info['label']}")
    if container.plugins.loaded:
        print("\nPlugins:")
        for plugin in container.plugins.catalog():
            print(f"  {plugin['name']} {plugin['version']} — {plugin['provides']}")
    return 0


def cmd_doctor(args: argparse.Namespace) -> int:
    """Check that the installation and the configured provider actually work."""

    async def run() -> int:
        container = _container()
        settings = container.settings
        ok = True
        print(f"DeckForge {__version__}")
        print(f"  data dir      : {settings.data_dir}")
        print(f"  database      : {settings.database_url}")

        await container.startup()
        print(f"  database ping : {'ok' if await container.database.ping() else 'FAILED'}")

        print(f"  themes        : {len(container.themes.names())}")
        print(f"  layouts       : {len(container.layouts.names())}")
        print(f"  exporters     : {', '.join(EXPORTERS.names())}")
        if container.plugins.errors:
            ok = False
            print(f"  plugin errors : {container.plugins.errors}")

        print(f"  provider      : {settings.default_provider} ({settings.default_model})")
        try:
            provider = container.providers.get()
            models = await provider.list_models()
            print(f"  reachable     : yes ({len(models)} models)")
            if settings.default_model not in models and models:
                print(f"  ! '{settings.default_model}' not found. available: {models[:6]}")
        except Exception as exc:
            ok = False
            print(f"  reachable     : NO — {exc}")

        await container.shutdown()
        print("\n" + ("All good." if ok else "Some checks failed (see above)."))
        return 0 if ok else 1

    return asyncio.run(run())


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="deckforge", description="DeckForge CLI")
    parser.add_argument("--version", action="version", version=f"DeckForge {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    serve = sub.add_parser("serve", help="run the API server")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8000)
    serve.add_argument("--reload", action="store_true")
    serve.set_defaults(func=cmd_serve)

    mcp = sub.add_parser("mcp", help="serve DeckForge to other agents over MCP (stdio)")
    mcp.set_defaults(func=cmd_mcp)

    sample = sub.add_parser("render-sample", help="render the sample deck as HTML")
    sample.add_argument("--theme", default="modern_dark")
    sample.add_argument("--out", default="sample.html")
    sample.add_argument("--notes", action="store_true", help="include speaker notes")
    sample.add_argument("--contact-sheet", action="store_true", help="all slides in a grid")
    sample.set_defaults(func=cmd_render_sample)

    export = sub.add_parser("export", help="export a deck")
    export.add_argument("--format", default="pptx", help=f"one of {EXPORTERS.names()}")
    export.add_argument("--deck", help="path to a deck JSON file (defaults to the sample deck)")
    export.add_argument("--theme")
    export.add_argument("--out")
    export.set_defaults(func=cmd_export)

    catalog = sub.add_parser("catalog", help="list themes, layouts, exporters and providers")
    catalog.set_defaults(func=cmd_catalog)

    doctor = sub.add_parser("doctor", help="check the installation and provider connectivity")
    doctor.set_defaults(func=cmd_doctor)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
