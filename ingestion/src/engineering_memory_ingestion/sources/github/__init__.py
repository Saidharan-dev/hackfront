"""GitHub source integration."""

from .adapter import ArtifactPage, GitHubAdapter
from .client import GitHubAPIError, GitHubClient, HTTPResponse, Page, Transport, UrlLibTransport
from .mapper import map_commit, map_pull_request

__all__ = [
    "ArtifactPage",
    "GitHubAPIError",
    "GitHubAdapter",
    "GitHubClient",
    "HTTPResponse",
    "Page",
    "Transport",
    "UrlLibTransport",
    "map_commit",
    "map_pull_request",
]
