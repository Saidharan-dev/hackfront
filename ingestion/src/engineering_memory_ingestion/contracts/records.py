"""Technology-neutral records exchanged by source adapters and the graph writer."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Mapping
from urllib.parse import quote


from .versions import SCHEMA_VERSION


class RecordKind(str, Enum):
    GIT_COMMIT = "git_commit"
    PULL_REQUEST = "pull_request"
    ISSUE = "issue"
    DISCUSSION_THREAD = "discussion_thread"
    DISCUSSION_MESSAGE = "discussion_message"


class RelationshipKind(str, Enum):
    PARENT_OF = "PARENT_OF"
    CHANGES = "CHANGES"
    REFERENCES = "REFERENCES"
    CONTAINS = "CONTAINS"
    REPLIES_TO = "REPLIES_TO"


def _required(value: str, name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")


def _timestamp(value: str, name: str) -> None:
    _required(value, name)
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{name} must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{name} must include a UTC offset")


@dataclass(frozen=True, slots=True)
class SourceIdentity:
    """A native identity, namespaced so IDs from different providers cannot collide."""

    provider: str
    workspace: str
    record_type: str
    source_id: str
    uri: str | None = None

    def __post_init__(self) -> None:
        for name in ("provider", "workspace", "record_type", "source_id"):
            _required(getattr(self, name), name)

    @property
    def canonical_id(self) -> str:
        parts = (self.provider, self.workspace, self.record_type, self.source_id)
        return ":".join(quote(part.strip(), safe="-._~") for part in parts)


@dataclass(frozen=True, slots=True)
class Actor:
    provider: str
    source_id: str
    display_name: str | None = None
    handle: str | None = None

    def __post_init__(self) -> None:
        _required(self.provider, "actor.provider")
        _required(self.source_id, "actor.source_id")


@dataclass(frozen=True, slots=True)
class Change:
    paths: tuple[str, ...] = ()
    additions: int | None = None
    deletions: int | None = None
    before: str | None = None
    after: str | None = None

    def __post_init__(self) -> None:
        if any(not isinstance(path, str) or not path.strip() for path in self.paths):
            raise ValueError("change paths must be non-empty strings")
        for name in ("additions", "deletions"):
            value = getattr(self, name)
            if value is not None and (not isinstance(value, int) or value < 0):
                raise ValueError(f"{name} must be a non-negative integer")


@dataclass(frozen=True, slots=True)
class Provenance:
    source_uri: str
    locator: str
    observed_at: str
    adapter_version: str
    payload_uri: str | None = None
    payload_sha256: str | None = None

    def __post_init__(self) -> None:
        for name in ("source_uri", "locator", "adapter_version"):
            _required(getattr(self, name), f"provenance.{name}")
        _timestamp(self.observed_at, "provenance.observed_at")
        if self.payload_sha256 is not None and (
            len(self.payload_sha256) != 64
            or any(char not in "0123456789abcdefABCDEF" for char in self.payload_sha256)
        ):
            raise ValueError("payload_sha256 must be a 64-character hexadecimal digest")


@dataclass(frozen=True, slots=True)
class SourceReference:
    target: SourceIdentity
    relationship: RelationshipKind
    locator: str

    def __post_init__(self) -> None:
        _required(self.locator, "reference.locator")


@dataclass(frozen=True, slots=True)
class Artifact:
    """Canonical record. `raw_payload` is opaque source evidence, never provider-parsed here."""

    source: SourceIdentity
    kind: RecordKind
    observed_at: str
    provenance: Provenance
    event_time: str | None = None
    updated_at: str | None = None
    actor: Actor | None = None
    title: str | None = None
    text: str | None = None
    context: Mapping[str, Any] = field(default_factory=dict)
    references: tuple[SourceReference, ...] = ()
    change: Change | None = None
    raw_payload: Mapping[str, Any] | None = field(default=None, repr=False, compare=False)
    schema_version: str = SCHEMA_VERSION

    def __post_init__(self) -> None:
        _timestamp(self.observed_at, "observed_at")
        if self.event_time is not None:
            _timestamp(self.event_time, "event_time")
        if self.updated_at is not None:
            _timestamp(self.updated_at, "updated_at")
        _required(self.schema_version, "schema_version")
        if self.raw_payload is None and self.provenance.payload_uri is None:
            raise ValueError("provide raw_payload or provenance.payload_uri")

    @property
    def canonical_id(self) -> str:
        return self.source.canonical_id
