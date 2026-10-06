"""Slack thread adapter."""

from __future__ import annotations

from dataclasses import dataclass

from ...contracts import Artifact
from .client import SlackClient
from .mapper import map_thread_message


@dataclass(frozen=True, slots=True)
class ArtifactPage:
    items: tuple[Artifact, ...]
    next_cursor: str | None


class SlackAdapter:
    def __init__(self, client: SlackClient):
        self.client = client

    def thread_page(
        self,
        workspace: str,
        channel: str,
        thread_ts: str,
        *,
        cursor: str | None = None,
        limit: int = 15,
    ) -> ArtifactPage:
        if not workspace:
            raise ValueError("workspace is required for stable Slack identities")
        page = self.client.thread_page(channel, thread_ts, cursor=cursor, limit=limit)
        return ArtifactPage(
            tuple(map_thread_message(message, workspace, channel, thread_ts) for message in page.items),
            page.next_cursor,
        )
