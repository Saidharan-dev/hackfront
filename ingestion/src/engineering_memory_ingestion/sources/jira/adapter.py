"""Jira issue and paginated comment adapter."""

from __future__ import annotations

from dataclasses import dataclass

from ...contracts import Artifact
from .client import JiraClient
from .mapper import map_comment, map_issue


@dataclass(frozen=True, slots=True)
class ArtifactPage:
    items: tuple[Artifact, ...]
    next_cursor: str | None


class JiraAdapter:
    def __init__(self, client: JiraClient, site: str):
        if not site.startswith("https://"):
            raise ValueError("site must be an HTTPS Jira URL")
        self.client = client
        self.site = site.rstrip("/")

    def issue(self, issue_key: str) -> Artifact:
        return map_issue(self.client.get_issue(issue_key), self.site)

    def comments_page(
        self,
        issue_key: str,
        *,
        cursor: str | None = None,
        per_page: int = 100,
    ) -> ArtifactPage:
        page = self.client.comments_page(issue_key, cursor=cursor, per_page=per_page)
        project = issue_key.split("-", 1)[0]
        return ArtifactPage(
            tuple(map_comment(comment, self.site, project, issue_key) for comment in page.items),
            page.next_cursor,
        )
