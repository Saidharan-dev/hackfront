"""Bounded, cursor-resumable orchestration over provider-neutral page fetchers."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable, Protocol

from ..contracts import Artifact, SCHEMA_VERSION
from ..extraction import EXTRACTION_VERSION
from ..observability import RunError, RunSummary
from ..observability.run_summary import cursor_fingerprint


class ArtifactPage(Protocol):
    items: tuple[Artifact, ...]
    next_cursor: str | None


class ArtifactWriter(Protocol):
    def write_artifact(self, artifact: Artifact) -> str: ...


PageFetcher = Callable[[str | None], ArtifactPage]


@dataclass(frozen=True, slots=True)
class IngestionRun:
    summary: RunSummary
    _resume_cursor: str | None = field(default=None, repr=False, compare=False)

    @property
    def resume_cursor(self) -> str | None:
        """Opaque cursor for programmatic replay; intentionally absent from summaries."""
        return self._resume_cursor


def _timestamp(artifact: Artifact) -> datetime | None:
    value = artifact.event_time or artifact.updated_at
    if value is None:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


def run_ingestion(
    *,
    source: str,
    fetch_page: PageFetcher,
    writer: ArtifactWriter,
    max_pages: int = 100,
    cursor: str | None = None,
    adapter_version: str = "unknown",
    schema_version: str = SCHEMA_VERSION,
    extraction_version: str = EXTRACTION_VERSION,
) -> IngestionRun:
    """Fetch and persist at most ``max_pages``; failed pages can be safely replayed."""
    for name, value in (("source", source), ("adapter_version", adapter_version),
                        ("schema_version", schema_version), ("extraction_version", extraction_version)):
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{name} must be a non-empty string")
    if type(max_pages) is not int or max_pages < 1:
        raise ValueError("max_pages must be a positive integer")

    initial_cursor = cursor
    resume_cursor = cursor
    requested_cursors: set[str | None] = set()
    page_count = fetched_count = normalized_count = persisted_count = 0
    timestamps: list[datetime] = []
    errors: list[RunError] = []
    complete = False

    for _ in range(max_pages):
        fingerprint = cursor_fingerprint(resume_cursor)
        if fingerprint in requested_cursors:
            errors.append(RunError("fetch", "CursorCycle", "Source repeated a page cursor"))
            break
        requested_cursors.add(fingerprint)
        page_cursor = resume_cursor
        try:
            page = fetch_page(page_cursor)
            items = page.items
            next_cursor = page.next_cursor
            if not isinstance(items, (tuple, list)) or any(not isinstance(item, Artifact) for item in items):
                raise TypeError("invalid page artifacts")
            if next_cursor is not None and not isinstance(next_cursor, str):
                raise TypeError("invalid page cursor")
        except Exception as error:
            resume_cursor = page_cursor
            errors.append(RunError("fetch_or_normalize", type(error).__name__, "Source page could not be fetched or normalized"))
            break

        page_count += 1
        fetched_count += len(items)
        normalized_count += len(items)
        for artifact in items:
            timestamp = _timestamp(artifact)
            if timestamp is not None:
                timestamps.append(timestamp)
            try:
                writer.write_artifact(artifact)
            except Exception as error:
                # Replay the page: stable artifact IDs make already-written items safe to upsert again.
                resume_cursor = page_cursor
                errors.append(RunError("persist", type(error).__name__, "Artifact could not be persisted; replay this page"))
                break
            persisted_count += 1
        else:
            resume_cursor = next_cursor
            if next_cursor is None:
                complete = True
                break
            continue
        break

    date_values = [value.isoformat().replace("+00:00", "Z") for value in timestamps]
    summary = RunSummary(
        source=source,
        cursor_start_sha256=cursor_fingerprint(initial_cursor),
        cursor_resume_sha256=cursor_fingerprint(resume_cursor),
        has_resume_cursor=resume_cursor is not None,
        pages_fetched=page_count,
        fetched_count=fetched_count,
        normalized_count=normalized_count,
        persisted_count=persisted_count,
        source_time_min=min(date_values) if date_values else None,
        source_time_max=max(date_values) if date_values else None,
        adapter_version=adapter_version,
        schema_version=schema_version,
        extraction_version=extraction_version,
        complete=complete and not errors,
        errors=tuple(errors),
    )
    return IngestionRun(summary, resume_cursor)
