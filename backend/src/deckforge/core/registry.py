"""A tiny, type-safe registry used by every extension point.

Providers, themes, layouts, exporters, agents and renderers are all registered
through instances of :class:`Registry`. Plugins mutate the registries at import
time, which is what makes the platform extensible without touching core code.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator, Mapping
from typing import Generic, TypeVar

from deckforge.core.errors import ConflictError, NotFoundError

T = TypeVar("T")


class Registry(Generic[T]):
    """A named collection of pluggable components."""

    def __init__(self, kind: str) -> None:
        self._kind = kind
        self._items: dict[str, T] = {}

    @property
    def kind(self) -> str:
        return self._kind

    def register(self, name: str, item: T, *, override: bool = False) -> T:
        """Register ``item`` under ``name``.

        Raises:
            ConflictError: if the name is taken and ``override`` is False.
        """
        key = name.strip().lower()
        if not key:
            raise ConflictError(f"{self._kind} name must not be empty")
        if key in self._items and not override:
            raise ConflictError(f"{self._kind} '{key}' is already registered")
        self._items[key] = item
        return item

    def unregister(self, name: str) -> None:
        self._items.pop(name.strip().lower(), None)

    def get(self, name: str) -> T:
        try:
            return self._items[name.strip().lower()]
        except KeyError as exc:
            raise NotFoundError(
                f"unknown {self._kind} '{name}'",
                details={"available": sorted(self._items)},
            ) from exc

    def try_get(self, name: str) -> T | None:
        return self._items.get(name.strip().lower())

    def names(self) -> list[str]:
        return sorted(self._items)

    def all(self) -> Mapping[str, T]:
        return dict(self._items)

    def decorator(self, name: str, *, override: bool = False) -> Callable[[type], type]:
        """Class decorator form of :meth:`register`."""

        def wrap(cls: type) -> type:
            self.register(name, cls, override=override)  # type: ignore[arg-type]
            return cls

        return wrap

    def __contains__(self, name: object) -> bool:
        return isinstance(name, str) and name.strip().lower() in self._items

    def __iter__(self) -> Iterator[str]:
        return iter(sorted(self._items))

    def __len__(self) -> int:
        return len(self._items)

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<Registry {self._kind}: {', '.join(sorted(self._items))}>"
