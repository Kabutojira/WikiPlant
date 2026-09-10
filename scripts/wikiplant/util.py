from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from datetime import datetime
from pathlib import PurePosixPath
from typing import Any

from .errors import ValidationError


UTC_SUFFIX = re.compile(r"(?:Z|[+-]\d\d:\d\d)$")


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def pretty_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n"


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_text(value: str) -> str:
    return sha256_bytes(value.encode("utf-8"))


def require_timestamp(value: str, field: str = "timestamp") -> datetime:
    if not value or not UTC_SUFFIX.search(value):
        raise ValidationError(f"{field} must have an explicit UTC/offset suffix")
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValidationError(f"{field} is not an ISO-8601 timestamp") from exc


def safe_relative_path(value: str) -> str:
    if not value or "\\" in value or "\x00" in value:
        raise ValidationError("path must be a nonempty POSIX relative path")
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise ValidationError(f"unsafe relative path: {value!r}")
    return str(path)


def slugify(value: str, max_length: int = 38) -> str:
    normalized = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    slug = re.sub(r"[^a-z0-9]+", "-", normalized.lower()).strip("-")
    return (slug or "instance")[:max_length].rstrip("-")


def normalize_question(value: str) -> str:
    value = unicodedata.normalize("NFKC", value).casefold()
    value = re.sub(r"[^\w\s-]", " ", value)
    return " ".join(value.split())


def ensure_single_line(value: str, field: str) -> str:
    if "\n" in value or "\r" in value:
        raise ValidationError(f"{field} must not contain CR/LF; link long prose instead")
    return value
