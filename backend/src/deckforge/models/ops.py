"""Deck operations — the edit language agents emit instead of whole decks.

Regenerating an entire presentation because the user asked to "move slide 7
before slide 4" is both slow and destructive. Editing agents therefore emit a
list of :class:`DeckOperation` objects which are applied *deterministically* in
Python. The LLM only decides *what* to change; the engine guarantees the deck
stays valid.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from deckforge.models.deck import (
    Background,
    DeckMetadata,
    Element,
    Presentation,
    Reference,
    Section,
    Slide,
    new_id,
)
from deckforge.models.enums import SlideKind
from deckforge.utils.structures import deep_merge


class OpBase(BaseModel):
    """Common configuration for operations."""

    model_config = ConfigDict(extra="ignore")

    reason: str | None = Field(
        default=None, description="Short user-facing explanation, surfaced in the changelog."
    )


class SetDeckMeta(OpBase):
    op: Literal["set_deck_meta"] = "set_deck_meta"
    title: str | None = None
    subtitle: str | None = None
    description: str | None = None
    meta: DeckMetadata | None = None


class SetTheme(OpBase):
    op: Literal["set_theme"] = "set_theme"
    theme: str | None = None
    overrides: dict[str, Any] | None = None
    merge: bool = True


class SetDeckBackground(OpBase):
    op: Literal["set_deck_background"] = "set_deck_background"
    background: Background | None = None


class AddSlide(OpBase):
    op: Literal["add_slide"] = "add_slide"
    slide: Slide
    index: int | None = None


class ReplaceSlide(OpBase):
    op: Literal["replace_slide"] = "replace_slide"
    slide_id: str
    slide: Slide


class UpdateSlide(OpBase):
    """Patch scalar fields on a slide; ``None`` means "leave unchanged"."""

    op: Literal["update_slide"] = "update_slide"
    slide_id: str
    title: str | None = None
    subtitle: str | None = None
    eyebrow: str | None = None
    notes: str | None = None
    kind: SlideKind | None = None
    layout: str | None = None
    section_id: str | None = None
    background: Background | None = None
    theme_overrides: dict[str, Any] | None = None
    hidden: bool | None = None
    locked: bool | None = None


class DeleteSlide(OpBase):
    op: Literal["delete_slide"] = "delete_slide"
    slide_id: str


class MoveSlide(OpBase):
    op: Literal["move_slide"] = "move_slide"
    slide_id: str
    to_index: int = Field(ge=0, description="Zero-based destination index.")


class DuplicateSlide(OpBase):
    op: Literal["duplicate_slide"] = "duplicate_slide"
    slide_id: str
    index: int | None = None


class MergeSlides(OpBase):
    op: Literal["merge_slides"] = "merge_slides"
    slide_ids: list[str]
    title: str | None = None


class SplitSlide(OpBase):
    op: Literal["split_slide"] = "split_slide"
    slide_id: str
    slides: list[Slide]


class SetElements(OpBase):
    """Replace the whole element list of a slide."""

    op: Literal["set_elements"] = "set_elements"
    slide_id: str
    elements: list[Element]


class UpsertElement(OpBase):
    op: Literal["upsert_element"] = "upsert_element"
    slide_id: str
    element: Element
    index: int | None = None


class DeleteElement(OpBase):
    op: Literal["delete_element"] = "delete_element"
    slide_id: str
    element_id: str


class AddSection(OpBase):
    op: Literal["add_section"] = "add_section"
    section: Section


class AddReference(OpBase):
    op: Literal["add_reference"] = "add_reference"
    reference: Reference
    slide_id: str | None = None


class ReorderSlides(OpBase):
    op: Literal["reorder_slides"] = "reorder_slides"
    slide_ids: list[str] = Field(
        description="Full or partial ordering; unlisted slides keep order."
    )


DeckOperation = Annotated[
    SetDeckMeta
    | SetTheme
    | SetDeckBackground
    | AddSlide
    | ReplaceSlide
    | UpdateSlide
    | DeleteSlide
    | MoveSlide
    | DuplicateSlide
    | MergeSlides
    | SplitSlide
    | SetElements
    | UpsertElement
    | DeleteElement
    | AddSection
    | AddReference
    | ReorderSlides,
    Field(discriminator="op"),
]


class OperationBatch(BaseModel):
    """What an editing agent returns."""

    model_config = ConfigDict(extra="ignore")

    summary: str = Field(default="", description="One-sentence summary shown to the user.")
    operations: list[DeckOperation] = Field(default_factory=list)


class OperationResult(BaseModel):
    """Outcome of applying a batch — feeds the conversation changelog."""

    applied: list[str] = Field(default_factory=list)
    skipped: list[str] = Field(default_factory=list)

    @property
    def changed(self) -> bool:
        return bool(self.applied)


def _clone_slide(slide: Slide) -> Slide:
    """Deep-copy a slide, assigning fresh ids so duplicates stay addressable."""
    copy = slide.model_copy(deep=True)
    copy.id = new_id("sl")
    for element in copy.elements:
        element.id = new_id("el")
    return copy


def apply_operations(deck: Presentation, operations: list[DeckOperation]) -> OperationResult:
    """Apply ``operations`` to ``deck`` in order, in place.

    Unknown slide ids are skipped rather than raising, because a model may
    reference a slide the user deleted mid-conversation. Locked slides are never
    modified.

    Returns:
        An :class:`OperationResult` listing human readable applied/skipped entries.
    """
    result = OperationResult()

    def _slide(slide_id: str, op_name: str) -> Slide | None:
        slide = deck.slide_by_id(slide_id)
        if slide is None:
            result.skipped.append(f"{op_name}: no slide {slide_id}")
            return None
        if slide.locked and op_name != "move_slide":
            result.skipped.append(f"{op_name}: slide {slide_id} is locked")
            return None
        return slide

    for op in operations:
        match op:
            case SetDeckMeta():
                if op.title:
                    deck.title = op.title
                if op.subtitle is not None:
                    deck.subtitle = op.subtitle
                if op.description is not None:
                    deck.description = op.description
                if op.meta is not None:
                    merged = deck.meta.model_dump() | op.meta.model_dump(exclude_none=True)
                    deck.meta = DeckMetadata.model_validate(merged)
                result.applied.append("updated deck details")

            case SetTheme():
                if op.theme:
                    deck.theme = op.theme
                    result.applied.append(f"switched theme to {op.theme}")
                if op.overrides is not None:
                    # Deep merge: "make the accent green" must not discard the
                    # primary colour set two turns ago.
                    deck.theme_overrides = (
                        deep_merge(deck.theme_overrides, op.overrides)
                        if op.merge
                        else dict(op.overrides)
                    )
                    result.applied.append("adjusted theme tokens")

            case SetDeckBackground():
                deck.background = op.background
                result.applied.append("changed deck background")

            case AddSlide():
                deck.add_slide(op.slide, op.index)
                result.applied.append(f"added slide '{op.slide.title or op.slide.id}'")

            case ReplaceSlide():
                idx = deck.index_of(op.slide_id)
                if idx < 0 or deck.slides[idx].locked:
                    result.skipped.append(f"replace_slide: {op.slide_id}")
                else:
                    op.slide.id = op.slide_id
                    deck.slides[idx] = op.slide
                    result.applied.append(f"rewrote slide {idx + 1}")

            case UpdateSlide():
                slide = _slide(op.slide_id, "update_slide")
                if slide is not None:
                    patch = op.model_dump(exclude_none=True, exclude={"op", "slide_id", "reason"})
                    for key, value in patch.items():
                        setattr(slide, key, value)
                    result.applied.append(f"updated slide {deck.index_of(slide.id) + 1}")

            case DeleteSlide():
                slide = deck.slide_by_id(op.slide_id)
                if slide is None or slide.locked:
                    result.skipped.append(f"delete_slide: {op.slide_id}")
                else:
                    position = deck.index_of(op.slide_id) + 1
                    deck.remove_slide(op.slide_id)
                    result.applied.append(f"deleted slide {position}")

            case MoveSlide():
                if deck.move_slide(op.slide_id, op.to_index):
                    result.applied.append(f"moved a slide to position {op.to_index + 1}")
                else:
                    result.skipped.append(f"move_slide: {op.slide_id}")

            case DuplicateSlide():
                source = deck.slide_by_id(op.slide_id)
                if source is None:
                    result.skipped.append(f"duplicate_slide: {op.slide_id}")
                else:
                    index = op.index if op.index is not None else deck.index_of(op.slide_id) + 1
                    deck.add_slide(_clone_slide(source), index)
                    result.applied.append("duplicated a slide")

            case MergeSlides():
                targets = [s for sid in op.slide_ids if (s := deck.slide_by_id(sid)) is not None]
                if len(targets) < 2:
                    result.skipped.append("merge_slides: need at least two existing slides")
                else:
                    primary = targets[0]
                    for extra in targets[1:]:
                        primary.elements.extend(extra.model_copy(deep=True).elements)
                        primary.notes = "\n\n".join(filter(None, (primary.notes, extra.notes)))
                        primary.references.extend(extra.references)
                        deck.remove_slide(extra.id)
                    if op.title:
                        primary.title = op.title
                    result.applied.append(f"merged {len(targets)} slides")

            case SplitSlide():
                idx = deck.index_of(op.slide_id)
                if idx < 0 or not op.slides:
                    result.skipped.append(f"split_slide: {op.slide_id}")
                else:
                    original = deck.slides[idx]
                    for new_slide in op.slides:
                        new_slide.section_id = new_slide.section_id or original.section_id
                    deck.slides[idx : idx + 1] = op.slides
                    result.applied.append(f"split a slide into {len(op.slides)}")

            case SetElements():
                slide = _slide(op.slide_id, "set_elements")
                if slide is not None:
                    slide.elements = list(op.elements)
                    result.applied.append(f"restyled slide {deck.index_of(slide.id) + 1}")

            case UpsertElement():
                slide = _slide(op.slide_id, "upsert_element")
                if slide is not None:
                    existing = slide.element_by_id(op.element.id)
                    if existing is not None:
                        slide.elements[slide.elements.index(existing)] = op.element
                    elif op.index is None:
                        slide.elements.append(op.element)
                    else:
                        slide.elements.insert(max(0, op.index), op.element)
                    result.applied.append("updated slide content")

            case DeleteElement():
                slide = _slide(op.slide_id, "delete_element")
                if slide is not None:
                    before = len(slide.elements)
                    slide.elements = [e for e in slide.elements if e.id != op.element_id]
                    if len(slide.elements) != before:
                        result.applied.append("removed an element")
                    else:
                        result.skipped.append(f"delete_element: {op.element_id}")

            case AddSection():
                deck.sections.append(op.section)
                result.applied.append(f"added section '{op.section.title}'")

            case AddReference():
                if op.slide_id:
                    slide = deck.slide_by_id(op.slide_id)
                    if slide is None:
                        result.skipped.append(f"add_reference: {op.slide_id}")
                        continue
                    slide.references.append(op.reference)
                else:
                    deck.references.append(op.reference)
                result.applied.append("added a reference")

            case ReorderSlides():
                # Snapshot the current positions first: reading them during the
                # sort would compare against a half-reordered list.
                positions = {existing.id: i for i, existing in enumerate(deck.slides)}
                order = {sid: i for i, sid in enumerate(op.slide_ids)}
                deck.slides.sort(key=lambda s: order.get(s.id, len(order) + positions.get(s.id, 0)))
                result.applied.append("reordered slides")

            case _:  # pragma: no cover - exhaustive over the union
                result.skipped.append("unknown operation")

    if result.changed:
        deck.touch()
    return result
