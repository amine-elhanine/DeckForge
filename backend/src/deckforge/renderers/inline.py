"""Inline markdown parsing for non-HTML renderers.

PPTX runs and PDF text spans both need `**bold**`, `*italic*` and `` `code` ``
broken into styled fragments. HTML gets this for free from the browser, so this
module exists purely for the binary exporters.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_PATTERN = re.compile(
    r"(?P<bold>\*\*(?P<bold_text>.+?)\*\*)"
    r"|(?P<italic>(?<!\*)\*(?P<italic_text>[^*]+?)\*(?!\*))"
    r"|(?P<code>`(?P<code_text>[^`]+?)`)"
    r"|(?P<link>\[(?P<link_text>[^\]]+)\]\((?P<link_href>[^)]+)\))",
    re.DOTALL,
)


@dataclass(slots=True)
class Span:
    """A styled run of text."""

    text: str
    bold: bool = False
    italic: bool = False
    code: bool = False
    href: str | None = None


def parse_inline(text: str) -> list[Span]:
    """Split ``text`` into styled spans.

    Unmatched markup is left as literal text, which keeps output predictable when
    a model emits half-formed markdown.
    """
    if not text:
        return []
    spans: list[Span] = []
    cursor = 0
    for match in _PATTERN.finditer(text):
        if match.start() > cursor:
            spans.append(Span(text[cursor : match.start()]))
        if match.group("bold"):
            spans.append(Span(match.group("bold_text"), bold=True))
        elif match.group("italic"):
            spans.append(Span(match.group("italic_text"), italic=True))
        elif match.group("code"):
            spans.append(Span(match.group("code_text"), code=True))
        elif match.group("link"):
            spans.append(Span(match.group("link_text"), href=match.group("link_href")))
        cursor = match.end()
    if cursor < len(text):
        spans.append(Span(text[cursor:]))
    return [s for s in spans if s.text]


def plain(text: str) -> str:
    """Strip inline markup, keeping the visible characters."""
    return "".join(span.text for span in parse_inline(text))
