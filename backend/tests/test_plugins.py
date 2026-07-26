"""Plugin loading and the extension points it reaches."""

from __future__ import annotations

from pathlib import Path

from deckforge.exporters.base import EXPORTERS
from deckforge.layouts.engine import LAYOUTS
from deckforge.plugins.loader import PluginManager
from deckforge.renderers.icons import ICONS
from deckforge.themes.engine import ThemeEngine

REPO_PLUGINS = Path(__file__).resolve().parents[2] / "plugins"

GOOD_PLUGIN = """
from deckforge.plugins import PluginManifest, PluginRegistry

MANIFEST = PluginManifest(name="tiny", version="0.1.0", description="test plugin")

def register(registry: PluginRegistry) -> None:
    registry.add_icon("tiny-mark", "M2 2h20v20H2z")
"""

BROKEN_PLUGIN = """
def register(registry):
    raise RuntimeError("this plugin is broken")
"""

NOT_A_PLUGIN = "VALUE = 1\n"


def test_example_plugin_contributes_every_extension_point() -> None:
    manager = PluginManager(search_paths=[REPO_PLUGINS])
    manager.load_all()

    assert not manager.errors
    names = {p.registry.manifest.name for p in manager.loaded}
    assert "example_brand" in names

    provides = next(
        p.registry.provides for p in manager.loaded if p.registry.manifest.name == "example_brand"
    )
    assert "exporters" in provides and "icons" in provides and "layouts" in provides

    assert "json" in EXPORTERS
    assert "brand_sidebar" in LAYOUTS
    assert "acme-mark" in ICONS

    # The plugin's theme directory becomes a normal theme source.
    engine = ThemeEngine(manager.theme_directories)
    assert "acme" in engine.names()


def test_plugin_theme_extends_a_builtin(settings) -> None:
    manager = PluginManager(search_paths=[REPO_PLUGINS])
    manager.load_all()
    engine = ThemeEngine([settings.builtin_theme_dir, *manager.theme_directories])
    acme = engine.get("acme")
    assert acme.palette.primary == "#c8102e"
    assert acme.palette.background == engine.get("minimal").palette.background


def test_plugin_exporter_round_trips(deck, themes, layouts, renderer) -> None:
    from deckforge.exporters.base import ExportContext
    from deckforge.models.deck import Presentation

    PluginManager(search_paths=[REPO_PLUGINS]).load_all()
    context = ExportContext(theme=themes.for_deck(deck), layouts=layouts, renderer=renderer)
    payload = EXPORTERS.get("json").export(deck, context).content
    assert Presentation.model_validate_json(payload).title == deck.title


def test_broken_plugin_is_isolated(tmp_path: Path) -> None:
    (tmp_path / "good").mkdir()
    (tmp_path / "good" / "__init__.py").write_text(GOOD_PLUGIN, encoding="utf-8")
    (tmp_path / "broken").mkdir()
    (tmp_path / "broken" / "__init__.py").write_text(BROKEN_PLUGIN, encoding="utf-8")
    (tmp_path / "inert").mkdir()
    (tmp_path / "inert" / "__init__.py").write_text(NOT_A_PLUGIN, encoding="utf-8")

    manager = PluginManager(search_paths=[tmp_path])
    manager.load_all()

    loaded = {p.module for p in manager.loaded}
    assert "good" in loaded
    assert "broken" not in loaded
    assert "inert" not in loaded
    assert len(manager.errors) == 1
    assert manager.errors[0]["plugin"] == "broken"
    assert "tiny-mark" in ICONS


def test_missing_plugin_directory_is_harmless(tmp_path: Path) -> None:
    manager = PluginManager(search_paths=[tmp_path / "does-not-exist"])
    assert manager.load_all() == []
    assert manager.errors == []
