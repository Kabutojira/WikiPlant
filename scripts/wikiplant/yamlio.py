"""A deliberately small YAML 1.2 subset for WikiPlant-owned configuration.

The parser accepts mappings, sequences, scalars, and JSON-style inline arrays.
It rejects anchors, tags, block scalars, duplicate keys, and tabs. This keeps the
runtime dependency-free and prevents a permissive loader from treating topic text
as executable/object-construction syntax.
"""

from __future__ import annotations

import json
import re
from typing import Any

from .errors import ValidationError


_KEY = re.compile(r"^[A-Za-z_][A-Za-z0-9_-]*$")


def _scalar(text: str) -> Any:
    text = text.strip()
    if text == "":
        return None
    if text in {"null", "~"}:
        return None
    if text == "true":
        return True
    if text == "false":
        return False
    if re.fullmatch(r"-?(0|[1-9]\d*)", text):
        return int(text)
    if text[:1] in {'"', "'"}:
        if text[0] == '"':
            try:
                return json.loads(text)
            except json.JSONDecodeError as exc:
                raise ValidationError("invalid quoted YAML scalar") from exc
        if not text.endswith("'"):
            raise ValidationError("unterminated YAML scalar")
        return text[1:-1].replace("''", "'")
    if text.startswith("[") or text.startswith("{"):
        try:
            return json.loads(text)
        except json.JSONDecodeError as exc:
            raise ValidationError("inline YAML collections must use JSON syntax") from exc
    if any(marker in text for marker in ("&", "*", "!", "|", ">")):
        raise ValidationError("unsupported YAML feature")
    return text


def loads(text: str) -> Any:
    if "\t" in text:
        raise ValidationError("tabs are not allowed in YAML")
    logical: list[tuple[int, str]] = []
    for number, raw in enumerate(text.splitlines(), 1):
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        indent = len(raw) - len(raw.lstrip(" "))
        if indent % 2:
            raise ValidationError(f"line {number}: indentation must use two spaces")
        logical.append((indent, raw.strip()))
    if not logical:
        return {}

    def parse_block(index: int, indent: int) -> tuple[Any, int]:
        is_list = logical[index][1].startswith("- ") or logical[index][1] == "-"
        result: Any = [] if is_list else {}
        while index < len(logical):
            current_indent, token = logical[index]
            if current_indent < indent:
                break
            if current_indent > indent:
                raise ValidationError("unexpected indentation")
            if is_list:
                if not token.startswith("-"):
                    raise ValidationError("cannot mix mapping and sequence at one indentation")
                rest = token[1:].strip()
                if not rest:
                    if index + 1 >= len(logical) or logical[index + 1][0] <= indent:
                        raise ValidationError("empty sequence item")
                    child, index = parse_block(index + 1, logical[index + 1][0])
                    result.append(child)
                    continue
                if ":" in rest and _KEY.fullmatch(rest.split(":", 1)[0]):
                    key, raw_value = rest.split(":", 1)
                    item: dict[str, Any] = {key: _scalar(raw_value)}
                    index += 1
                    while index < len(logical) and logical[index][0] > indent:
                        child_indent, child_token = logical[index]
                        if child_indent != indent + 2 or ":" not in child_token:
                            raise ValidationError("invalid sequence mapping indentation")
                        child_key, child_raw = child_token.split(":", 1)
                        if child_key in item or not _KEY.fullmatch(child_key):
                            raise ValidationError("invalid or duplicate YAML key")
                        if child_raw.strip():
                            item[child_key] = _scalar(child_raw)
                            index += 1
                        else:
                            if index + 1 >= len(logical) or logical[index + 1][0] <= child_indent:
                                item[child_key] = None
                                index += 1
                            else:
                                child, index = parse_block(index + 1, logical[index + 1][0])
                                item[child_key] = child
                    result.append(item)
                    continue
                result.append(_scalar(rest))
                index += 1
            else:
                if token.startswith("-") or ":" not in token:
                    raise ValidationError("expected YAML mapping entry")
                key, raw_value = token.split(":", 1)
                if not _KEY.fullmatch(key) or key in result:
                    raise ValidationError("invalid or duplicate YAML key")
                if raw_value.strip():
                    result[key] = _scalar(raw_value)
                    index += 1
                elif index + 1 < len(logical) and logical[index + 1][0] > indent:
                    child, index = parse_block(index + 1, logical[index + 1][0])
                    result[key] = child
                else:
                    result[key] = None
                    index += 1
        return result, index

    value, end = parse_block(0, logical[0][0])
    if end != len(logical):
        raise ValidationError("unparsed YAML content")
    return value


def _quote(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def dumps(value: Any, indent: int = 0) -> str:
    lines: list[str] = []

    def emit(node: Any, level: int, key: str | None = None) -> None:
        prefix = " " * level
        if key is not None:
            if isinstance(node, dict):
                lines.append(f"{prefix}{key}:")
                for child_key, child in node.items():
                    emit(child, level + 2, child_key)
                return
            if isinstance(node, list):
                if not node:
                    lines.append(f"{prefix}{key}: []")
                else:
                    lines.append(f"{prefix}{key}:")
                    for child in node:
                        emit(child, level + 2)
                return
            lines.append(f"{prefix}{key}: {_format_scalar(node)}")
            return
        if isinstance(node, dict):
            if not node:
                lines.append(f"{prefix}- {{}}")
            else:
                entries = list(node.items())
                first_key, first_child = entries[0]
                if isinstance(first_child, dict):
                    lines.append(f"{prefix}- {first_key}:")
                    for nested_key, nested_child in first_child.items():
                        emit(nested_child, level + 4, nested_key)
                elif isinstance(first_child, list):
                    if not first_child:
                        lines.append(f"{prefix}- {first_key}: []")
                    else:
                        lines.append(f"{prefix}- {first_key}:")
                        for nested_child in first_child:
                            emit(nested_child, level + 4)
                else:
                    lines.append(f"{prefix}- {first_key}: {_format_scalar(first_child)}")
                for child_key, child in entries[1:]:
                    emit(child, level + 2, child_key)
            return
        lines.append(f"{prefix}- {_format_scalar(node)}")

    def _format_scalar(node: Any) -> str:
        if node is None:
            return "null"
        if node is True:
            return "true"
        if node is False:
            return "false"
        if isinstance(node, int):
            return str(node)
        return _quote(str(node))

    if not isinstance(value, dict):
        raise ValidationError("top-level WikiPlant YAML must be a mapping")
    for root_key, root_value in value.items():
        emit(root_value, indent, root_key)
    return "\n".join(lines) + "\n"
