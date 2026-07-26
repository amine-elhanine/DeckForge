"""Composition root.

Every long-lived dependency is constructed exactly once, here, and injected
downwards. Nothing below this module reaches for a global singleton, which is
what keeps the layers testable in isolation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from deckforge import paths
from deckforge.config import Settings, get_settings
from deckforge.core.logging import configure_logging, get_logger
from deckforge.database.repositories import UnitOfWork
from deckforge.database.session import Database
from deckforge.exporters.base import EXPORTERS
from deckforge.layouts.engine import LayoutEngine
from deckforge.plugins.loader import PluginManager
from deckforge.providers.registry import ProviderFactory
from deckforge.renderers.html import HtmlRenderer
from deckforge.themes.engine import ThemeEngine

log = get_logger(__name__)


@dataclass(slots=True)
class Container:
    """Holds the application's singletons."""

    settings: Settings
    database: Database
    themes: ThemeEngine
    layouts: LayoutEngine
    renderer: HtmlRenderer
    providers: ProviderFactory
    plugins: PluginManager = field(default_factory=PluginManager)

    @classmethod
    def create(cls, settings: Settings | None = None) -> Container:
        """Build the container, loading plugins before the engines read the registries."""
        settings = settings or get_settings()
        configure_logging(settings.log_level, settings.log_format)
        settings.ensure_directories()

        plugins = PluginManager(search_paths=cls._plugin_paths(settings))
        plugins.load_all()

        themes = ThemeEngine(
            [settings.builtin_theme_dir, *settings.theme_paths, *plugins.theme_directories]
        )
        layouts = LayoutEngine()
        container = cls(
            settings=settings,
            database=Database(settings),
            themes=themes,
            layouts=layouts,
            renderer=HtmlRenderer(layouts),
            providers=ProviderFactory(settings),
            plugins=plugins,
        )
        log.info(
            "container.ready",
            themes=len(themes.names()),
            layouts=len(layouts.names()),
            exporters=EXPORTERS.names(),
            plugins=[p.module for p in plugins.loaded],
        )
        return container

    @staticmethod
    def _plugin_paths(settings: Settings) -> list[Path]:
        """Shipped plugins, the user's own, and anything configured explicitly."""
        return [*paths.bundled_plugin_dirs(), *settings.plugin_paths]

    async def startup(self) -> None:
        """Create tables and load database-backed configuration."""
        await self.database.create_all()
        async with self.database.session() as session:
            uow = UnitOfWork.create(session)
            await uow.users.get_or_create_local()
            await self._load_database_themes(uow)
            await self._bootstrap_llm(uow)

    async def shutdown(self) -> None:
        await self.providers.aclose()
        await self.database.dispose()

    async def _load_database_themes(self, uow: UnitOfWork) -> None:
        for record in await uow.themes.all_records():
            self.themes.add_definition(record.name, record.definition, source="database")

    async def _bootstrap_llm(self, uow: UnitOfWork) -> None:
        """Turn an environment-configured provider into a first saved connection.

        Someone who already put a key in ``.env`` should not have to retype it in
        the settings screen on first launch.
        """
        from deckforge.services.llm_service import LlmService

        await LlmService(uow, self.settings, self.providers).bootstrap_from_env()
