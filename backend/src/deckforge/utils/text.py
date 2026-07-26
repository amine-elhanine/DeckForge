"""Text helpers used by the writer, critic and retrieval layers."""

from __future__ import annotations

import math
import re
import unicodedata
from collections import Counter

_WORD_RE = re.compile(r"[A-Za-z0-9_À-ɏЀ-ӿ؀-ۿ]+")
_SENTENCE_RE = re.compile(r"(?<=[.!?])\s+")

STOPWORDS = frozenset(
    [
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "by",
        "for",
        "from",
        "has",
        "have",
        "how",
        "i",
        "in",
        "is",
        "it",
        "its",
        "of",
        "on",
        "or",
        "that",
        "the",
        "this",
        "to",
        "was",
        "were",
        "what",
        "when",
        "where",
        "which",
        "who",
        "will",
        "with",
        "you",
        "your",
        "we",
        "our",
        "us",
        "they",
        "their",
        "there",
        "here",
        "about",
        "into",
        "over",
        "under",
        "more",
        "most",
        "some",
        "such",
        "only",
        "own",
        "same",
        "than",
        "too",
        "very",
        "can",
        "just",
        "should",
        "now",
    ]
)


def tokenize(text: str) -> list[str]:
    """Lowercase word tokens with stopwords removed."""
    return [t.lower() for t in _WORD_RE.findall(text) if t.lower() not in STOPWORDS and len(t) > 1]


def sentences(text: str) -> list[str]:
    return [s.strip() for s in _SENTENCE_RE.split(text.strip()) if s.strip()]


def slugify(value: str, max_length: int = 60) -> str:
    """Return a filesystem- and URL-safe slug."""
    normalized = unicodedata.normalize("NFKD", value)
    ascii_only = normalized.encode("ascii", "ignore").decode()
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", ascii_only).strip("-").lower()
    return (slug or "untitled")[:max_length].rstrip("-")


def truncate(text: str, limit: int, suffix: str = "…") -> str:
    """Truncate on a word boundary when possible."""
    if len(text) <= limit:
        return text
    cut = text[: max(0, limit - len(suffix))]
    if " " in cut:
        cut = cut[: cut.rfind(" ")]
    return cut.rstrip() + suffix


def estimate_tokens(text: str) -> int:
    """Rough token estimate (~4 chars/token) good enough for budgeting."""
    return max(1, math.ceil(len(text) / 4))


def title_case(value: str) -> str:
    """Sentence-style title casing that leaves acronyms intact."""
    words = value.strip().split()
    if not words:
        return ""
    out: list[str] = []
    for i, word in enumerate(words):
        if word.isupper() and len(word) <= 5:
            out.append(word)
        elif i == 0:
            out.append(word[0].upper() + word[1:])
        else:
            out.append(word)
    return " ".join(out)


def strip_markdown(text: str) -> str:
    """Remove the small subset of markdown we allow in slide text."""
    out = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", text)
    out = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", out)
    out = re.sub(r"[*_`~]{1,3}", "", out)
    out = re.sub(r"^\s{0,3}#{1,6}\s*", "", out, flags=re.MULTILINE)
    out = re.sub(r"^\s{0,3}[-*+]\s+", "", out, flags=re.MULTILINE)
    return out.strip()


def bullet_split(text: str) -> list[str]:
    """Split a model's blob into bullet lines."""
    lines = [line.strip(" -*•\t") for line in text.splitlines()]
    return [line for line in lines if line]


def jaccard(a: str, b: str) -> float:
    """Token-set similarity — used to detect repeated slide content."""
    ta, tb = set(tokenize(a)), set(tokenize(b))
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


def keyword_summary(text: str, limit: int = 8) -> list[str]:
    """Return the most frequent meaningful tokens."""
    return [word for word, _ in Counter(tokenize(text)).most_common(limit)]


def fit_lines(text: str, chars_per_line: int) -> int:
    """Estimate how many rendered lines ``text`` needs at a given measure."""
    if chars_per_line <= 0:
        return 1
    total = 0
    for paragraph in text.splitlines() or [""]:
        total += max(1, math.ceil(len(paragraph) / chars_per_line))
    return max(1, total)
