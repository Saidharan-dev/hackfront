"""Map Jira REST issues and comments into source-neutral artifacts."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Mapping

from ...contracts import Actor, Artifact, Provenance, RecordKind, RelationshipKind, SourceIdentity, SourceReference

ADAPTER_VERSION = "jira-cloud-rest/0.1"


def _text(value: object) -> str | None:
    return value if isinstance(value, str) and value.strip() else None


def _plain_text(value: object) -> str | None:
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        if value.get("type") == "text":
            return _text(value.get("text"))
        content = value.get("content")
        if isinstance(content, list):
            return "".join(filter(None, (_plain_text(child) for child in content))) or None
        return _text(value.get("text"))
    if isinstance(value, list):
        return "".join(filter(None, (_plain_text(child) for child in value))) or None
    return None


def _time(value: object) -> str | None:
    text = _text(value)
    if not text:
        return None
    parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("Jira timestamp must include a UTC offset")
    return parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _provenance(payload: Mapping[str, object], uri: str, locator: str) -> Provenance:
    return Provenance(
        source_uri=_text(payload.get("self")) or uri,
        locator=locator,
        observed_at=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        adapter_version=ADAPTER_VERSION,
    )


def map_issue(payload: Mapping[str, object], site: str) -> Artifact:
    key = _text(payload.get("key"))
    if not key:
        raise ValueError("Jira issue payload requires key")
    fields = payload.get("fields") if isinstance(payload.get("fields"), dict) else {}
    project = fields.get("project") if isinstance(fields.get("project"), dict) else {}
    project_key = _text(project.get("key"))
    workspace = project_key or site
    issue_type = fields.get("issuetype") if isinstance(fields.get("issuetype"), dict) else {}
    status = fields.get("status") if isinstance(fields.get("status"), dict) else {}
    priority = fields.get("priority") if isinstance(fields.get("priority"), dict) else {}
    reporter = fields.get("reporter") if isinstance(fields.get("reporter"), dict) else {}
    links = fields.get("issuelinks") if isinstance(fields.get("issuelinks"), list) else []
    references = []
    for index, link in enumerate(links):
        if not isinstance(link, dict):
            continue
        target = link.get("outwardIssue") or link.get("inwardIssue")
        target_key = _text(target.get("key")) if isinstance(target, dict) else None
        if target_key:
            references.append(SourceReference(
                SourceIdentity("jira", workspace, "issue", target_key),
                RelationshipKind.REFERENCES,
                f"$.fields.issuelinks[{index}]",
            ))
    source = SourceIdentity("jira", workspace, "issue", key, _text(payload.get("self")))
    uri = f"{site.rstrip('/')}/rest/api/3/issue/{key}"
    return Artifact(
        source=source,
        kind=RecordKind.ISSUE,
        event_time=_time(fields.get("created")),
        updated_at=_time(fields.get("updated")),
        observed_at=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        actor=Actor("jira", str(reporter.get("accountId") or "unknown"), _text(reporter.get("displayName"))) if reporter else None,
        title=_text(fields.get("summary")),
        text=_plain_text(fields.get("description")),
        context={
            "project_key": project_key,
            "issue_type": _text(issue_type.get("name")),
            "status": _text(status.get("name")),
            "priority": _text(priority.get("name")),
            "labels": tuple(item for item in fields.get("labels", []) if isinstance(item, str))
            if isinstance(fields.get("labels"), list) else (),
        },
        references=tuple(references),
        provenance=_provenance(payload, uri, "$.fields"),
        raw_payload=payload,
    )


def map_comment(payload: Mapping[str, object], site: str, project: str, issue_key: str) -> Artifact:
    comment_id = payload.get("id")
    if not isinstance(comment_id, (str, int)) or not str(comment_id):
        raise ValueError("Jira comment payload requires id")
    author = payload.get("author") if isinstance(payload.get("author"), dict) else {}
    uri = f"{site.rstrip('/')}/rest/api/3/issue/{issue_key}/comment/{comment_id}"
    return Artifact(
        source=SourceIdentity("jira", project, "comment", str(comment_id), _text(payload.get("self"))),
        kind=RecordKind.DISCUSSION_MESSAGE,
        event_time=_time(payload.get("created")),
        updated_at=_time(payload.get("updated")),
        observed_at=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        actor=Actor("jira", str(author.get("accountId") or "unknown"), _text(author.get("displayName"))) if author else None,
        text=_plain_text(payload.get("body")),
        context={"issue_key": issue_key},
        references=(SourceReference(SourceIdentity("jira", project, "issue", issue_key), RelationshipKind.REFERENCES, "$.issue"),),
        provenance=_provenance(payload, uri, "$.body"),
        raw_payload=payload,
    )
