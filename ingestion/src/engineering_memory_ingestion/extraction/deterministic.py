"""Deterministic evidence extraction from normalized source artifacts."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Mapping

from ..contracts import Artifact

EXTRACTION_VERSION = "deterministic/0.1"


@dataclass(frozen=True, slots=True)
class ExtractedValue:
    field: str
    value: Any
    locator: str
    extraction_version: str = EXTRACTION_VERSION

    def __post_init__(self) -> None:
        if not self.field or not self.locator or not self.extraction_version:
            raise ValueError("extracted values require a field, source locator, and extraction version")


@dataclass(frozen=True, slots=True)
class ExtractionResult:
    canonical_id: str
    values: tuple[ExtractedValue, ...]

    def values_for(self, field: str) -> tuple[ExtractedValue, ...]:
        return tuple(value for value in self.values if value.field == field)


def _source_id_locator(artifact: Artifact) -> str:
    provider, record_type = artifact.source.provider, artifact.source.record_type
    if provider == "github":
        return "$.sha" if record_type == "commit" else "$.number" if record_type == "pull_request" else "$.id"
    if provider == "jira":
        return "$.key" if record_type == "issue" else "$.id"
    if provider == "slack":
        return "$.ts"
    return artifact.provenance.locator


def _time_locator(artifact: Artifact, field: str) -> str:
    provider, record_type = artifact.source.provider, artifact.source.record_type
    payload = artifact.raw_payload or {}
    if provider == "github":
        if field == "event_time":
            if record_type == "commit":
                commit = payload.get("commit") if isinstance(payload.get("commit"), dict) else {}
                author = commit.get("author") if isinstance(commit.get("author"), dict) else {}
                return "$.commit.author.date" if artifact.event_time == author.get("date") else "$.commit.committer.date"
            if record_type == "pull_request":
                return "$.created_at"
            return "$.submitted_at" if payload.get("submitted_at") is not None else "$.created_at"
        return "$.updated_at"
    if provider == "jira":
        prefix = "$.fields." if record_type == "issue" else "$."
        return prefix + ("created" if field == "event_time" else "updated")
    if provider == "slack":
        return "$.ts"
    return artifact.provenance.locator


def _url_locator(payload: Mapping[str, Any], fallback: str) -> str:
    for key in ("html_url", "self", "url"):
        if isinstance(payload.get(key), str) and payload[key]:
            return f"$.{key}"
    return fallback


def _actor_locator(artifact: Artifact) -> str:
    provider, record_type = artifact.source.provider, artifact.source.record_type
    payload = artifact.raw_payload or {}
    if provider == "github":
        if record_type == "commit":
            if isinstance(payload.get("author"), dict) and payload["author"].get("id"):
                return "$.author.id"
            commit = payload.get("commit") if isinstance(payload.get("commit"), dict) else {}
            author = commit.get("author") if isinstance(commit.get("author"), dict) else {}
            return "$.commit.author.email" if artifact.actor.source_id == author.get("email") else "$.commit.author.name"
        return "$.user.id"
    if provider == "jira":
        return "$.fields.reporter.accountId" if record_type == "issue" else "$.author.accountId"
    if provider == "slack":
        return "$.bot_id" if payload.get("bot_id") else "$.user"
    return artifact.provenance.locator


def _path_locators(artifact: Artifact) -> tuple[str, ...]:
    if artifact.source.record_type != "commit":
        return tuple("$.path" for _ in (artifact.change.paths if artifact.change else ()))
    files = artifact.raw_payload.get("files") if artifact.raw_payload and isinstance(artifact.raw_payload.get("files"), list) else []
    locators = []
    next_index = 0
    for path in artifact.change.paths if artifact.change else ():
        for index in range(next_index, len(files)):
            item = files[index]
            if isinstance(item, dict) and item.get("filename") == path:
                locators.append(f"$.files[{index}].filename")
                next_index = index + 1
                break
        else:
            locators.append(artifact.provenance.locator)
    return tuple(locators)


def _utc_timestamp(value: str) -> str:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("extracted timestamps must include a UTC offset")
    return parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _diff_values(artifact: Artifact) -> tuple[ExtractedValue, ...]:
    if artifact.source.provider != "github":
        return ()
    raw = artifact.raw_payload or {}
    if artifact.source.record_type == "commit":
        files = raw.get("files") if isinstance(raw.get("files"), list) else []
        return tuple(
            ExtractedValue("diff", item["patch"], f"$.files[{index}].patch")
            for index, item in enumerate(files)
            if isinstance(item, dict) and isinstance(item.get("patch"), str)
        )
    diff_hunk = raw.get("diff_hunk")
    return (ExtractedValue("diff", diff_hunk, "$.diff_hunk"),) if isinstance(diff_hunk, str) else ()


def extract_deterministic(artifact: Artifact) -> ExtractionResult:
    """Return source-grounded values; free text is retained but never interpreted."""
    raw: Mapping[str, Any] = artifact.raw_payload or {}
    values = [
        ExtractedValue("source_id", artifact.source.source_id, _source_id_locator(artifact)),
        ExtractedValue("canonical_id", artifact.canonical_id, _source_id_locator(artifact)),
        ExtractedValue("source_uri", artifact.source.uri or artifact.provenance.source_uri,
                       _url_locator(raw, artifact.provenance.locator)),
        ExtractedValue("provenance", artifact.provenance, artifact.provenance.locator),
    ]
    if artifact.event_time:
        values.append(ExtractedValue("event_time", _utc_timestamp(artifact.event_time), _time_locator(artifact, "event_time")))
    if artifact.updated_at:
        values.append(ExtractedValue("updated_at", _utc_timestamp(artifact.updated_at), _time_locator(artifact, "updated_at")))
    if artifact.actor:
        values.append(ExtractedValue("actor_id", artifact.actor.source_id, _actor_locator(artifact)))
    if artifact.change:
        for path, locator in zip(artifact.change.paths, _path_locators(artifact)):
            values.append(ExtractedValue("path", path, locator))
        for name in ("additions", "deletions", "before", "after"):
            value = getattr(artifact.change, name)
            if value is not None:
                locator = f"$.stats.{name}" if artifact.source.record_type == "commit" else f"$.{name}"
                values.append(ExtractedValue(name, value, locator))
    values.extend(_diff_values(artifact))
    for reference in artifact.references:
        values.append(ExtractedValue(
            "reference",
            {"target": reference.target.canonical_id, "relationship": reference.relationship.value},
            reference.locator,
        ))
    return ExtractionResult(artifact.canonical_id, tuple(values))
