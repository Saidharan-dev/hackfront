"""Metadata-only summaries that never serialize cursors or source content."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass


def cursor_fingerprint(cursor: str | None) -> str | None:
    """Return a stable diagnostic identifier without exposing an opaque cursor."""
    if cursor is None:
        return None
    return hashlib.sha256(cursor.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class RunError:
    stage: str
    error_type: str
    message: str

    def to_dict(self) -> dict[str, str]:
        return {"stage": self.stage, "type": self.error_type, "message": self.message}


@dataclass(frozen=True, slots=True)
class RunSummary:
    source: str
    cursor_start_sha256: str | None
    cursor_resume_sha256: str | None
    has_resume_cursor: bool
    pages_fetched: int
    fetched_count: int
    normalized_count: int
    persisted_count: int
    source_time_min: str | None
    source_time_max: str | None
    adapter_version: str
    schema_version: str
    extraction_version: str
    complete: bool
    errors: tuple[RunError, ...] = ()

    def to_dict(self) -> dict[str, object]:
        """Export only safe metadata; never include raw cursors or source payloads."""
        return {
            "source": self.source,
            "cursor_range": {
                "start_sha256": self.cursor_start_sha256,
                "resume_sha256": self.cursor_resume_sha256,
                "has_resume_cursor": self.has_resume_cursor,
            },
            "counts": {
                "pages_fetched": self.pages_fetched,
                "fetched": self.fetched_count,
                "normalized": self.normalized_count,
                "persisted": self.persisted_count,
            },
            "source_time_range": {"min": self.source_time_min, "max": self.source_time_max},
            "versions": {
                "adapter": self.adapter_version,
                "schema": self.schema_version,
                "extraction": self.extraction_version,
            },
            "complete": self.complete,
            "errors": [error.to_dict() for error in self.errors],
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":"))
