"""Map GitHub REST payloads to the source-neutral record contract."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Mapping

from ...contracts import (
    Actor,
    Artifact,
    Change,
    Provenance,
    RecordKind,
    RelationshipKind,
    SourceIdentity,
    SourceReference,
)

ADAPTER_VERSION = "github-rest/0.1"


def _text(value: object) -> str | None:
    return value if isinstance(value, str) and value.strip() else None


def _count(value: object) -> int | None:
    return value if isinstance(value, int) and value >= 0 else None


def _actor(provider: Mapping[str, object] | None, fallback: Mapping[str, object] | None = None) -> Actor | None:
    data = provider or {}
    fallback = fallback or {}
    source_id = data.get("id") or data.get("login") or fallback.get("email") or fallback.get("name")
    if source_id is None:
        return None
    return Actor(
        provider="github",
        source_id=str(source_id),
        display_name=_text(data.get("login")) or _text(fallback.get("name")),
        handle=_text(data.get("login")),
    )


def _observed_at() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _provenance(payload: Mapping[str, object], source_uri: str, locator: str) -> Provenance:
    return Provenance(
        source_uri=_text(payload.get("url")) or source_uri,
        locator=locator,
        observed_at=_observed_at(),
        adapter_version=ADAPTER_VERSION,
    )


def map_commit(payload: Mapping[str, object], owner: str, repository: str) -> Artifact:
    sha = _text(payload.get("sha"))
    commit = payload.get("commit")
    if not sha or not isinstance(commit, dict):
        raise ValueError("GitHub commit payload requires sha and commit object")
    metadata_author = commit.get("author") if isinstance(commit.get("author"), dict) else {}
    metadata_committer = commit.get("committer") if isinstance(commit.get("committer"), dict) else {}
    message = _text(commit.get("message")) or ""
    parents = payload.get("parents") if isinstance(payload.get("parents"), list) else []
    references = tuple(
        SourceReference(
            target=SourceIdentity("github", f"{owner}/{repository}", "commit", str(parent["sha"]), _text(parent.get("url"))),
            relationship=RelationshipKind.REFERENCES,
            locator=f"$.parents[{index}].sha",
        )
        for index, parent in enumerate(parents)
        if isinstance(parent, dict) and _text(parent.get("sha"))
    )
    stats = payload.get("stats") if isinstance(payload.get("stats"), dict) else {}
    files = payload.get("files") if isinstance(payload.get("files"), list) else []
    paths = tuple(
        str(file["filename"])
        for file in files
        if isinstance(file, dict) and _text(file.get("filename"))
    )
    author = payload.get("author") if isinstance(payload.get("author"), dict) else None
    source = SourceIdentity(
        "github", f"{owner}/{repository}", "commit", sha, _text(payload.get("html_url"))
    )
    source_uri = f"https://api.github.com/repos/{owner}/{repository}/commits/{sha}"
    return Artifact(
        source=source,
        kind=RecordKind.GIT_COMMIT,
        event_time=_text(metadata_author.get("date")) or _text(metadata_committer.get("date")),
        observed_at=_observed_at(),
        actor=_actor(author, metadata_author),
        title=message.splitlines()[0] if message else None,
        text=message or None,
        context={"repository": f"{owner}/{repository}"},
        references=references,
        change=Change(
            paths=paths,
            additions=_count(stats.get("additions")),
            deletions=_count(stats.get("deletions")),
        ),
        provenance=_provenance(payload, source_uri, "$"),
        raw_payload=payload,
    )


def map_pull_request(payload: Mapping[str, object], owner: str, repository: str) -> Artifact:
    number = payload.get("number")
    if not isinstance(number, (int, str)) or not str(number).strip():
        raise ValueError("GitHub pull request payload requires number")
    head = payload.get("head") if isinstance(payload.get("head"), dict) else {}
    base = payload.get("base") if isinstance(payload.get("base"), dict) else {}
    merged_sha = _text(payload.get("merge_commit_sha"))
    references: list[SourceReference] = []
    for locator, branch, relationship in (
        ("$.head.sha", head, RelationshipKind.CONTAINS),
        ("$.base.sha", base, RelationshipKind.REFERENCES),
    ):
        sha = _text(branch.get("sha"))
        if sha:
            references.append(SourceReference(
                SourceIdentity("github", f"{owner}/{repository}", "commit", sha),
                relationship,
                locator,
            ))
    if merged_sha:
        references.append(SourceReference(
            SourceIdentity("github", f"{owner}/{repository}", "commit", merged_sha),
            RelationshipKind.REFERENCES,
            "$.merge_commit_sha",
        ))
    user = payload.get("user") if isinstance(payload.get("user"), dict) else None
    source_uri = f"https://api.github.com/repos/{owner}/{repository}/pulls/{number}"
    source = SourceIdentity(
        "github", f"{owner}/{repository}", "pull_request", str(number), _text(payload.get("html_url"))
    )
    return Artifact(
        source=source,
        kind=RecordKind.PULL_REQUEST,
        event_time=_text(payload.get("created_at")),
        updated_at=_text(payload.get("updated_at")),
        observed_at=_observed_at(),
        actor=_actor(user),
        title=_text(payload.get("title")),
        text=_text(payload.get("body")),
        context={
            "repository": f"{owner}/{repository}",
            "state": _text(payload.get("state")),
            "merged": payload.get("merged") if isinstance(payload.get("merged"), bool) else None,
            "head_ref": _text(head.get("ref")),
            "base_ref": _text(base.get("ref")),
        },
        references=tuple(references),
        change=Change(
            additions=_count(payload.get("additions")),
            deletions=_count(payload.get("deletions")),
        ),
        provenance=_provenance(payload, source_uri, "$"),
        raw_payload=payload,
    )


def map_pull_request_activity(
    payload: Mapping[str, object],
    owner: str,
    repository: str,
    pull_number: int,
    activity: str,
) -> Artifact:
    """Map a review or PR comment while preserving its native discussion evidence."""
    record_types = {
        "reviews": "pull_request_review",
        "review_comments": "pull_request_review_comment",
        "issue_comments": "pull_request_issue_comment",
    }
    if activity not in record_types:
        raise ValueError(f"unsupported pull-request activity: {activity}")
    native_id = payload.get("id")
    if not isinstance(native_id, (str, int)) or not str(native_id).strip():
        raise ValueError("GitHub pull-request activity requires id")
    user = payload.get("user") if isinstance(payload.get("user"), dict) else None
    source_uri = _text(payload.get("url")) or _text(payload.get("html_url")) or (
        f"https://api.github.com/repos/{owner}/{repository}/pulls/{pull_number}/{activity}"
    )
    pull_identity = SourceIdentity(
        "github", f"{owner}/{repository}", "pull_request", str(pull_number),
        f"https://github.com/{owner}/{repository}/pull/{pull_number}",
    )
    references = [SourceReference(
        pull_identity,
        RelationshipKind.REFERENCES,
        f"endpoint:/repos/{owner}/{repository}/pulls/{pull_number}/{activity}",
    )]
    parent_comment_id = payload.get("in_reply_to_id")
    if activity == "review_comments" and isinstance(parent_comment_id, (str, int)):
        references.append(SourceReference(
            SourceIdentity(
                "github", f"{owner}/{repository}", record_types[activity], str(parent_comment_id)
            ),
            RelationshipKind.REPLIES_TO,
            "$.in_reply_to_id",
        ))
    body = _text(payload.get("body"))
    state = _text(payload.get("state"))
    path = _text(payload.get("path"))
    context: dict[str, object] = {"pull_request_number": pull_number, "activity_kind": activity}
    for key in ("state", "commit_id", "diff_hunk", "line", "original_line", "author_association"):
        value = payload.get(key)
        if isinstance(value, (str, int)):
            context[key] = value
    source = SourceIdentity(
        "github", f"{owner}/{repository}", record_types[activity], str(native_id),
        _text(payload.get("html_url")),
    )
    event_time = _text(payload.get("submitted_at")) or _text(payload.get("created_at"))
    return Artifact(
        source=source,
        kind=RecordKind.DISCUSSION_MESSAGE,
        event_time=event_time,
        updated_at=_text(payload.get("updated_at")),
        observed_at=_observed_at(),
        actor=_actor(user),
        title=(f"Review: {state}" if activity == "reviews" and state else None),
        text=body,
        context=context,
        references=tuple(references),
        change=Change(paths=(path,) if path else ()),
        provenance=_provenance(payload, source_uri, "$"),
        raw_payload=payload,
    )
