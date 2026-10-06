"""Map native Slack thread replies into thread and message artifacts."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Mapping
from urllib.parse import urlencode

from ...contracts import Actor, Artifact, Provenance, RecordKind, RelationshipKind, SourceIdentity, SourceReference

ADAPTER_VERSION = "slack-web-api/0.1"


def _event_time(value: object) -> str:
    if not isinstance(value, str):
        raise ValueError("Slack message requires timestamp")
    try:
        timestamp = float(Decimal(value))
        return datetime.fromtimestamp(timestamp, timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")
    except (InvalidOperation, OverflowError, OSError, ValueError):
        raise ValueError("Slack message timestamp must be a Unix timestamp") from None


def _observed_at() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def map_thread_message(
    payload: Mapping[str, object], workspace: str, channel: str, thread_ts: str,
) -> Artifact:
    ts = payload.get("ts")
    if not isinstance(ts, str) or not ts:
        raise ValueError("Slack message requires ts")
    root = ts == thread_ts
    record_type = "thread" if root else "message"
    source = SourceIdentity("slack", workspace, record_type, ts)
    user_id = payload.get("user") or payload.get("bot_id")
    actor = Actor("slack", str(user_id)) if user_id else None
    references = () if root else (SourceReference(
        SourceIdentity("slack", workspace, "thread", thread_ts),
        RelationshipKind.REPLIES_TO,
        "$.thread_ts",
    ),)
    locator = f"$.messages[?(@.ts=='{ts}')]"
    context = {
        "channel_id": channel,
        "thread_ts": thread_ts,
        "reply_count": payload.get("reply_count") if isinstance(payload.get("reply_count"), int) else None,
        "subtype": payload.get("subtype") if isinstance(payload.get("subtype"), str) else None,
    }
    return Artifact(
        source=source,
        kind=RecordKind.DISCUSSION_THREAD if root else RecordKind.DISCUSSION_MESSAGE,
        event_time=_event_time(ts),
        observed_at=_observed_at(),
        actor=actor,
        text=payload.get("text") if isinstance(payload.get("text"), str) else None,
        context=context,
        references=references,
        provenance=Provenance(
            source_uri=f"https://slack.com/api/conversations.replies?{urlencode({'channel': channel, 'ts': thread_ts})}",
            locator=locator,
            observed_at=_observed_at(),
            adapter_version=ADAPTER_VERSION,
        ),
        raw_payload=payload,
    )
