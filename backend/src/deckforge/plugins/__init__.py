"""Plugin system: install capabilities without touching core code."""

from deckforge.plugins.loader import LoadedPlugin, PluginManager
from deckforge.plugins.spec import PluginManifest, PluginRegistry

__all__ = ["LoadedPlugin", "PluginManager", "PluginManifest", "PluginRegistry"]
