"""Tolerant JSON extraction for LLM output.

Small local models routinely wrap JSON in prose or code fences, emit trailing
commas, or use single quotes. Rather than failing the run we repair what we can
and only then ask the model to try again.
"""

from __future__ import annotations

import json
import re
from typing import Any, TypeVar

from pydantic import BaseModel, ValidationError

_FENCE_RE = re.compile(r"```(?:json|jsonc|json5)?\s*(.*?)```", re.DOTALL | re.IGNORECASE)
_TRAILING_COMMA_RE = re.compile(r",\s*([}\]])")
_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")

T = TypeVar("T", bound=BaseModel)


def _balanced_slice(text: str, open_ch: str, close_ch: str) -> str | None:
    """Return the first balanced ``open_ch``…``close_ch`` region, ignoring string bodies."""
    start = text.find(open_ch)
    if start < 0:
        return None
    depth = 0
    in_string = False
    escape = False
    for i in range(start, len(text)):
        ch = text[i]
        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch == open_ch:
            depth += 1
        elif ch == close_ch:
            depth -= 1
            if depth == 0:
                return text[start : i + 1]
    return None


def extract_json_text(raw: str) -> str | None:
    """Pull the most plausible JSON document out of ``raw``."""
    if not raw:
        return None
    candidates: list[str] = []
    for match in _FENCE_RE.findall(raw):
        candidates.append(match.strip())
    candidates.append(raw.strip())
    for candidate in candidates:
        for open_ch, close_ch in (("{", "}"), ("[", "]")):
            sliced = _balanced_slice(candidate, open_ch, close_ch)
            if sliced:
                return sliced
    return None


def repair_json(text: str) -> str:
    """Apply conservative fixes that never change valid JSON semantics."""
    fixed = _CONTROL_RE.sub("", text)
    fixed = _TRAILING_COMMA_RE.sub(r"\1", fixed)
    fixed = fixed.replace("“", '"').replace("”", '"')
    fixed = fixed.replace("﻿", "")
    return fixed.strip()


def loads(raw: str) -> Any:
    """Parse JSON from possibly-messy model output.

    Raises:
        ValueError: if nothing parseable can be recovered.
    """
    candidate = extract_json_text(raw)
    if candidate is None:
        raise ValueError("no JSON object found in model output")
    try:
        return json.loads(candidate)
    except json.JSONDecodeError:
        pass
    try:
        return json.loads(repair_json(candidate))
    except json.JSONDecodeError as exc:
        raise ValueError(f"could not parse JSON: {exc}") from exc


def parse_model(raw: str, model: type[T]) -> T:
    """Parse ``raw`` into ``model``.

    Raises:
        ValueError: on unparseable JSON or schema violations.
    """
    data = loads(raw)
    if isinstance(data, list):
        # A model that returns a bare list when an object was requested usually
        # meant the object's single list field.
        fields = [n for n, f in model.model_fields.items() if f.annotation is not None]
        list_fields = [n for n in fields if "list" in str(model.model_fields[n].annotation).lower()]
        if len(list_fields) == 1:
            data = {list_fields[0]: data}
    try:
        return model.model_validate(data)
    except ValidationError as exc:
        raise ValueError(
            f"schema mismatch for {model.__name__}: {exc.error_count()} errors"
        ) from exc


def schema_hint(model: type[BaseModel]) -> str:
    """Render a compact JSON-schema hint to embed in a prompt."""
    schema = model.model_json_schema()
    schema.pop("title", None)
    return json.dumps(schema, ensure_ascii=False, separators=(",", ":"))
