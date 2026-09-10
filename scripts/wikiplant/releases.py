"""Release decisions over complete, freshly fetched metadata; no provider calls."""
from __future__ import annotations

import copy
import re
from dataclasses import asdict, dataclass, field
from functools import total_ordering
from typing import Any

from .errors import ValidationError
from .util import pretty_json, require_timestamp, sha256_text


@total_ordering
@dataclass(frozen=True)
class Version:
    major: int
    minor: int
    patch: int
    prerelease: tuple[str, ...] = ()

    @classmethod
    def parse(cls, text: str) -> "Version":
        match = re.fullmatch(r"v?(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(?:-([0-9A-Za-z.-]+))?(?:\+([0-9A-Za-z.-]+))?", text)
        if not match:
            raise ValidationError("release versions must use semantic major.minor.patch")
        pre = tuple(match[4].split(".")) if match[4] else ()
        identifiers = (*pre, *(match[5].split(".") if match[5] else ()))
        if any(not value for value in identifiers) or any(value.isdigit() and len(value) > 1 and value[0] == "0" for value in pre):
            raise ValidationError("invalid semantic version identifier")
        return cls(int(match[1]), int(match[2]), int(match[3]), pre)

    def __lt__(self, other: object) -> bool:
        if not isinstance(other, Version):
            return NotImplemented
        own, theirs = (self.major, self.minor, self.patch), (other.major, other.minor, other.patch)
        if own != theirs:
            return own < theirs
        if not self.prerelease or not other.prerelease:
            return bool(self.prerelease) and not other.prerelease
        for left, right in zip(self.prerelease, other.prerelease):
            if left == right:
                continue
            if left.isdigit() and right.isdigit():
                return int(left) < int(right)
            if left.isdigit() != right.isdigit():
                return left.isdigit()
            return left < right
        return len(self.prerelease) < len(other.prerelease)


@dataclass(frozen=True)
class ReleaseInfo:
    repository: str
    release_id: str
    version: str
    tag: str
    source_commit: str
    manifest_sha256: str
    published_at: str
    read_schemas: tuple[int, ...] = (2,)
    write_schema: int = 2
    migrations: tuple[str, ...] = ()
    required_capabilities: tuple[str, ...] = ()
    draft: bool = False
    prerelease: bool = False
    immutable: bool = False
    summary: str = ""

    def validate(self) -> None:
        if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", self.repository) or not self.release_id:
            raise ValidationError("release requires a trusted repository and provider release ID")
        Version.parse(self.version)
        if Version.parse(self.tag) != Version.parse(self.version):
            raise ValidationError("release tag/version mismatch")
        if not re.fullmatch(r"[a-f0-9]{40}", self.source_commit) or not re.fullmatch(r"[a-f0-9]{64}", self.manifest_sha256):
            raise ValidationError("release requires resolved commit and detached manifest digest")
        require_timestamp(self.published_at, "release published_at")
        if not self.read_schemas or any(type(v) is not int or v < 1 for v in self.read_schemas) or type(self.write_schema) is not int or self.write_schema not in self.read_schemas or len(set(self.read_schemas)) != len(self.read_schemas):
            raise ValidationError("invalid release schema compatibility")

    @property
    def identity(self) -> str:
        return sha256_text(pretty_json({"repository": self.repository, "release_id": self.release_id, "version": self.version,
                                       "tag": self.tag, "source_commit": self.source_commit, "manifest_sha256": self.manifest_sha256}))

    def compatibility(self, schema: int, capabilities: set[str]) -> tuple[bool, list[str]]:
        gaps = [f"missing capability: {cap}" for cap in self.required_capabilities if cap not in capabilities]
        if schema != self.write_schema and f"{schema}_to_{self.write_schema}" not in self.migrations:
            gaps.append(f"missing migration {schema}_to_{self.write_schema}")
        if schema == self.write_schema and schema not in self.read_schemas:
            gaps.append(f"cannot read schema {schema}")
        return not gaps, gaps


@dataclass
class ReleaseCheckState:
    instance_id: str
    repository: str
    installed_version: str
    last_successful_check: str | None = None
    successful_week: str | None = None
    outcome: str = "not_checked"
    known_versions: dict[str, str] = field(default_factory=dict)
    notices: dict[str, dict] = field(default_factory=dict)
    attempts: dict[str, int] = field(default_factory=dict)
    retry_at: str | None = None
    newest_stable: str | None = None
    newest_compatible: str | None = None
    error: str | None = None
    schema_version: int = 2

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: dict) -> "ReleaseCheckState":
        if value.get("schema_version") != 2:
            raise ValidationError("unsupported release-check state")
        return cls(**copy.deepcopy(value))


def check_releases(state: ReleaseCheckState, releases: list[ReleaseInfo] | None, *, week_key: str, checked_at: str,
                   schema: int, capabilities: set[str], complete: bool, fresh: bool,
                   error: str | None = None, channel: str = "stable", max_releases: int = 100,
                   retry_after_seconds: int = 3600, max_attempts_per_week: int = 3) -> list[dict[str, Any]]:
    """Mutate serialized state only after metadata observations; caller saves before notifying.

    ``None`` is retrieval failure. An observed complete empty list is ``no_release``.
    Notices persist their publication payload independently of observation of delivery.
    """
    from datetime import timedelta
    now = require_timestamp(checked_at, "release checked_at")
    if channel not in {"stable", "prerelease"} or not week_key or max_releases < 1 or retry_after_seconds < 1 or max_attempts_per_week < 1:
        raise ValidationError("invalid release-check policy")
    if state.successful_week == week_key:
        return []
    if state.retry_at and now < require_timestamp(state.retry_at, "release retry_at"):
        return []
    if state.attempts.get(week_key, 0) >= max_attempts_per_week:
        return []
    state.attempts[week_key] = state.attempts.get(week_key, 0) + 1
    if error or releases is None or not complete or not fresh or len(releases) > max_releases:
        state.outcome = "failed"
        state.error = error or "release inventory is missing, partial, stale, or exceeds bounded coverage"
        state.retry_at = (now + timedelta(seconds=retry_after_seconds)).isoformat()
        return []
    candidates: list[ReleaseInfo] = []
    alerts = []
    known_versions = dict(state.known_versions)
    try:
        for release in releases:
            if release.draft:
                continue
            release.validate()
            if release.repository != state.repository:
                raise ValidationError("release repository differs from trusted installation provenance")
            key = str(Version.parse(release.version))
            known = known_versions.get(key)
            if known and known != release.identity:
                alerts.append(f"identity changed for known version {release.version}")
            else:
                known_versions[key] = release.identity
            if channel == "stable" and (release.prerelease or Version.parse(release.version).prerelease):
                continue
            candidates.append(release)
    except ValidationError as exc:
        state.outcome, state.error = "failed", str(exc)
        state.retry_at = (now + timedelta(seconds=retry_after_seconds)).isoformat()
        return []
    if alerts:
        state.outcome, state.error = "security_alert", "; ".join(alerts)
        state.retry_at = (now + timedelta(seconds=retry_after_seconds)).isoformat()
        return []
    candidates.sort(key=lambda item: Version.parse(item.version), reverse=True)
    state.known_versions = known_versions
    stable = [item for item in candidates if not item.prerelease and not Version.parse(item.version).prerelease]
    state.newest_stable = stable[0].version if stable else None
    compatible = [item for item in candidates if item.compatibility(schema, capabilities)[0]]
    state.newest_compatible = compatible[0].version if compatible else None
    state.last_successful_check, state.successful_week = checked_at, week_key
    state.retry_at, state.error = None, None
    newer = [item for item in candidates if Version.parse(item.version) > Version.parse(state.installed_version)]
    state.outcome = "available" if newer else "up_to_date" if candidates else "no_release"
    created = []
    if newer:
        candidate = newer[0]
        notice_id = "update-" + sha256_text(state.instance_id + ":" + candidate.identity)[:24]
        if notice_id not in state.notices:
            ok, reasons = candidate.compatibility(schema, capabilities)
            notice = {"schema_version": 2, "id": notice_id, "instance_id": state.instance_id,
                      "installed_version": state.installed_version, "release": asdict(candidate),
                      "compatible": ok, "blockers": reasons, "saved_reference": None,
                      "result_published": False, "notification_observed": None,
                      "publication_payload": f"WikiPlant {candidate.version} is available; this instance uses {state.installed_version}. "
                      + ("Compatible update available. " if ok else "Update blocked: " + "; ".join(reasons) + ". ")
                      + "No update has been applied."}
            state.notices[notice_id] = notice
            created.append(copy.deepcopy(notice))
    return created


class ReleaseCheckStore:
    """Snapshot-bound durable check/notice storage; provider fetching stays outside."""
    def __init__(self, writer, state_binding, notice_folder_id: str, *, repository: str, installed_version: str):
        self.writer, self.state_binding, self.notice_folder_id = writer, state_binding, notice_folder_id
        self.repository, self.installed_version = repository, installed_version

    def load(self):
        import json
        from .storage import validate_binding
        snapshot = validate_binding(self.writer.adapter, self.state_binding, self.writer.root_id)
        value = json.loads(snapshot.content)
        state = ReleaseCheckState.from_dict(value) if value else ReleaseCheckState(self.writer.instance_id, self.repository, self.installed_version)
        if (state.instance_id, state.repository) != (self.writer.instance_id, self.repository):
            raise ValidationError("release check state belongs to another instance/repository")
        state.installed_version = self.installed_version
        return snapshot, state

    def _save(self, snapshot, state):
        body = pretty_json(state.to_dict()).encode()
        self.writer.replace(self.state_binding, body,
                            f"{state.instance_id}:release-check:{snapshot.revision}:{sha256_text(body.decode())}", base=snapshot)

    def check(self, releases, **options):
        from .storage import create_artifact
        snapshot, state = self.load()
        created = check_releases(state, releases, **options)
        for notice in created:
            observed = create_artifact(self.writer.adapter, self.writer.root_id, self.notice_folder_id,
                                       notice["id"] + ".json", notice, f"{state.instance_id}:notice:{notice['id']}")
            state.notices[notice["id"]]["saved_reference"] = observed.id
            notice["saved_reference"] = observed.id
        self._save(snapshot, state)
        return state, created

    def publish(self, notice_id: str, *, publish_result, reconcile_result) -> dict:
        """Publish exactly the persisted payload; uncertain outcomes require reconciliation."""
        from .storage import validate_scope
        snapshot, state = self.load()
        notice = state.notices.get(notice_id)
        if not notice or not notice.get("saved_reference"):
            raise ValidationError("notice must be durably saved before publication")
        if notice["result_published"]:
            return copy.deepcopy(notice)
        saved = validate_scope(self.writer.adapter, notice["saved_reference"], self.writer.root_id)
        import json
        if json.loads(saved.content)["publication_payload"] != notice["publication_payload"]:
            raise ValidationError("saved notice differs from publication payload")
        observed = reconcile_result(notice_id)
        if observed is None:
            observed = publish_result(notice_id, notice["publication_payload"])
        if not isinstance(observed, str) or not observed:
            raise ValidationError("native result publication needs an observed result reference")
        notice["result_published"] = True
        notice["publication_reference"] = observed
        self._save(snapshot, state)
        return copy.deepcopy(notice)
