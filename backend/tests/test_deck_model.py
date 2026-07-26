"""Deck model and operation language."""

from __future__ import annotations

import pytest

from deckforge.models.deck import BulletsElement, Presentation, Slide, TextElement
from deckforge.models.enums import SlideKind
from deckforge.models.ops import (
    AddSlide,
    DeleteElement,
    DeleteSlide,
    DuplicateSlide,
    MergeSlides,
    MoveSlide,
    ReorderSlides,
    SetTheme,
    SplitSlide,
    UpdateSlide,
    UpsertElement,
    apply_operations,
)


@pytest.fixture
def small_deck() -> Presentation:
    deck = Presentation(title="Test deck")
    for i in range(5):
        deck.add_slide(Slide(title=f"Slide {i + 1}", notes=f"note {i + 1}"))
    return deck


def test_round_trips_through_json(deck: Presentation) -> None:
    restored = Presentation.model_validate(deck.model_dump(mode="json"))
    assert restored.model_dump(mode="json") == deck.model_dump(mode="json")
    assert len(restored.slides) == len(deck.slides)


def test_bullets_accept_bare_strings() -> None:
    element = BulletsElement.model_validate({"type": "bullets", "items": ["a", "b"]})
    assert [i.text for i in element.items] == ["a", "b"]


def test_text_content_flattens_every_element(deck: Presentation) -> None:
    cover = deck.slides[0]
    assert "Reinforcement Learning" in cover.text_content()
    chart_slide = next(s for s in deck.slides if s.kind is SlideKind.CHART)
    assert chart_slide.word_count() > 0


def test_move_slide_reorders(small_deck: Presentation) -> None:
    target = small_deck.slides[3].id
    apply_operations(small_deck, [MoveSlide(slide_id=target, to_index=0)])
    assert small_deck.slides[0].id == target
    assert len(small_deck.slides) == 5


def test_move_slide_seven_before_four() -> None:
    """The canonical user request must land the slide in the right place."""
    deck = Presentation(title="Ordering")
    for i in range(8):
        deck.add_slide(Slide(title=f"S{i + 1}"))
    seventh = deck.slides[6].id
    apply_operations(deck, [MoveSlide(slide_id=seventh, to_index=3)])
    assert [s.title for s in deck.slides] == ["S1", "S2", "S3", "S7", "S4", "S5", "S6", "S8"]


def test_delete_and_add(small_deck: Presentation) -> None:
    doomed = small_deck.slides[1].id
    result = apply_operations(
        small_deck,
        [DeleteSlide(slide_id=doomed), AddSlide(slide=Slide(title="New"), index=0)],
    )
    assert result.changed
    assert small_deck.slide_by_id(doomed) is None
    assert small_deck.slides[0].title == "New"


def test_locked_slides_are_never_modified(small_deck: Presentation) -> None:
    small_deck.slides[0].locked = True
    result = apply_operations(
        small_deck, [UpdateSlide(slide_id=small_deck.slides[0].id, title="Changed")]
    )
    assert small_deck.slides[0].title == "Slide 1"
    assert result.skipped


def test_unknown_slide_is_skipped_not_fatal(small_deck: Presentation) -> None:
    result = apply_operations(small_deck, [DeleteSlide(slide_id="sl_missing")])
    assert not result.changed
    assert result.skipped


def test_merge_and_split(small_deck: Presentation) -> None:
    a, b = small_deck.slides[0].id, small_deck.slides[1].id
    small_deck.slides[0].elements.append(TextElement(text="left"))
    small_deck.slides[1].elements.append(TextElement(text="right"))
    apply_operations(small_deck, [MergeSlides(slide_ids=[a, b], title="Merged")])
    assert len(small_deck.slides) == 4
    merged = small_deck.slide_by_id(a)
    assert merged is not None and merged.title == "Merged"
    assert len(merged.elements) == 2
    assert "note 1" in merged.notes and "note 2" in merged.notes

    apply_operations(
        small_deck,
        [SplitSlide(slide_id=a, slides=[Slide(title="Part 1"), Slide(title="Part 2")])],
    )
    assert [s.title for s in small_deck.slides[:2]] == ["Part 1", "Part 2"]


def test_duplicate_gets_fresh_ids(small_deck: Presentation) -> None:
    source = small_deck.slides[0]
    source.elements.append(TextElement(text="body"))
    apply_operations(small_deck, [DuplicateSlide(slide_id=source.id)])
    copy = small_deck.slides[1]
    assert copy.id != source.id
    assert copy.elements[0].id != source.elements[0].id
    assert copy.elements[0].text == "body"  # type: ignore[union-attr]


def test_element_upsert_and_delete(small_deck: Presentation) -> None:
    slide = small_deck.slides[0]
    element = TextElement(text="hello")
    apply_operations(small_deck, [UpsertElement(slide_id=slide.id, element=element)])
    assert len(slide.elements) == 1

    element.text = "updated"
    apply_operations(small_deck, [UpsertElement(slide_id=slide.id, element=element)])
    assert len(slide.elements) == 1
    assert slide.elements[0].text == "updated"  # type: ignore[union-attr]

    apply_operations(small_deck, [DeleteElement(slide_id=slide.id, element_id=element.id)])
    assert slide.elements == []


def test_reorder_keeps_unlisted_slides(small_deck: Presentation) -> None:
    ids = [s.id for s in small_deck.slides]
    apply_operations(small_deck, [ReorderSlides(slide_ids=[ids[4], ids[3]])])
    assert small_deck.slides[0].id == ids[4]
    assert small_deck.slides[1].id == ids[3]
    assert len(small_deck.slides) == 5


def test_set_theme_merges_overrides(small_deck: Presentation) -> None:
    apply_operations(
        small_deck, [SetTheme(theme="neon", overrides={"palette": {"primary": "#f00"}})]
    )
    apply_operations(small_deck, [SetTheme(overrides={"palette": {"accent": "#0f0"}})])
    assert small_deck.theme == "neon"
    assert small_deck.theme_overrides["palette"] == {"primary": "#f00", "accent": "#0f0"}


def test_stats_and_outline(deck: Presentation) -> None:
    stats = deck.stats()
    assert stats["slides"] == len(deck.slides)
    assert stats["distinct_layouts"] >= 1
    assert "(id=" in deck.outline_text()


def test_sections_group_slides(deck: Presentation) -> None:
    groups = list(deck.iter_sections())
    assert len(groups) >= 2
    assert sum(len(slides) for _, slides in groups) == len(deck.slides)
