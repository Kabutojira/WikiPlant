"""Authorization records supplied by the trusted current-turn host boundary.

Language interpretation produces a proposal; this module never treats a source
document or a keyword match as a grant. The host must supply turn provenance and
an affirmative semantic decision, including flags for quoted/negated intent.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
import re

from .errors import ValidationError
from .util import sha256_text


@dataclass(frozen=True)
class UserAuthorization:
    user_turn_ref: str
    instance_id: str
    operation: str
    target: str
    request_sha256: str
    affirmative: bool
    reason: str
    source_role: str = "current_user"
    negated: bool = False
    quoted: bool = False
    hypothetical: bool = False
    informational: bool = False
    schema_version: int = 2

    def validate(self, *, instance_id: str, operation: str, target: str) -> None:
        for field in ("affirmative", "negated", "quoted", "hypothetical", "informational"):
            if type(getattr(self, field)) is not bool:
                raise ValidationError("authorization flags must be JSON booleans")
        for field in ("user_turn_ref", "instance_id", "operation", "target", "request_sha256", "reason", "source_role"):
            if not isinstance(getattr(self, field), str) or not getattr(self, field).strip():
                raise ValidationError("authorization identity and provenance must be nonempty strings")
        if self.schema_version != 2 or self.source_role != "current_user" or not self.user_turn_ref:
            raise ValidationError("authorization requires actual current user-turn provenance")
        if (self.instance_id, self.operation, self.target) != (instance_id, operation, target):
            raise ValidationError("authorization instance/operation/target mismatch")
        if not self.affirmative or any((self.negated, self.quoted, self.hypothetical, self.informational)):
            raise ValidationError("request is not an affirmative mutation directive")
        if not self.reason.strip() or not re.fullmatch(r"[a-f0-9]{64}", self.request_sha256):
            raise ValidationError("authorization needs a reason and original request digest")

    def to_dict(self) -> dict:
        return asdict(self)


def validate_user_authorization(value: dict, *, instance_id: str, operation: str, target: str) -> UserAuthorization:
    if not isinstance(value, dict):
        raise ValidationError("a keyword/string authorization is not a user-turn grant")
    try:
        grant = UserAuthorization(**value)
    except TypeError as exc:
        raise ValidationError("malformed user authorization") from exc
    grant.validate(instance_id=instance_id, operation=operation, target=target)
    return grant


def request_digest(request: str) -> str:
    return sha256_text(request)
