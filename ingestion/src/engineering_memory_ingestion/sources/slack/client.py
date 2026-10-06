"""Slack conversations.replies client with injectable transport and page cursors."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Mapping, Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener


API_URL = "https://slack.com/api/conversations.replies"
MAX_PAGE_SIZE = 15


class SlackAPIError(RuntimeError):
    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status


@dataclass(frozen=True, slots=True)
class HTTPResponse:
    status: int
    headers: Mapping[str, str]
    body: bytes


class Transport(Protocol):
    def get(self, url: str, headers: Mapping[str, str], timeout: float) -> HTTPResponse: ...


class _SlackRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        old, new = urlsplit(req.full_url), urlsplit(newurl)
        if (new.scheme, new.hostname, new.port) != (old.scheme, old.hostname, old.port):
            return None
        return super().redirect_request(req, fp, code, msg, headers, newurl)


class UrlLibTransport:
    def get(self, url: str, headers: Mapping[str, str], timeout: float) -> HTTPResponse:
        try:
            with build_opener(_SlackRedirect()).open(
                Request(url, headers=dict(headers), method="GET"), timeout=timeout
            ) as response:
                return HTTPResponse(response.status, dict(response.headers.items()), response.read())
        except HTTPError as error:
            error.close()
            raise SlackAPIError(f"Slack API returned HTTP {error.code}", error.code) from None
        except URLError:
            raise SlackAPIError("Slack API transport failed") from None
        except TimeoutError:
            raise SlackAPIError("Slack API request timed out") from None


@dataclass(frozen=True, slots=True)
class Page:
    items: tuple[Mapping[str, object], ...]
    next_cursor: str | None


class SlackClient:
    def __init__(self, token: str | None = None, *, transport: Transport | None = None, timeout: float = 30.0):
        self.token = token
        self.transport = transport or UrlLibTransport()
        self.timeout = timeout

    @classmethod
    def from_environment(cls, **kwargs) -> "SlackClient":
        return cls(os.environ.get("SLACK_BOT_TOKEN"), **kwargs)

    def thread_page(
        self,
        channel: str,
        thread_ts: str,
        *,
        cursor: str | None = None,
        limit: int = MAX_PAGE_SIZE,
    ) -> Page:
        if not channel or not thread_ts:
            raise ValueError("channel and thread_ts are required")
        if not 1 <= limit <= MAX_PAGE_SIZE:
            raise ValueError(f"limit must be between 1 and {MAX_PAGE_SIZE}")
        params = {"channel": channel, "ts": thread_ts, "limit": limit}
        if cursor:
            params["cursor"] = cursor
        response = self.transport.get(
            f"{API_URL}?{urlencode(params)}",
            {
                "Accept": "application/json",
                "User-Agent": "engineering-memory-ingestion/0.1",
                **({"Authorization": f"Bearer {self.token}"} if self.token else {}),
            },
            self.timeout,
        )
        if not 200 <= response.status < 300:
            raise SlackAPIError(f"Slack API returned HTTP {response.status}", response.status)
        try:
            payload = json.loads(response.body)
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise SlackAPIError("Slack API returned invalid JSON", response.status) from None
        if not isinstance(payload, dict) or payload.get("ok") is not True:
            raise SlackAPIError("Slack API returned an unsuccessful response", response.status)
        messages = payload.get("messages")
        metadata = payload.get("response_metadata")
        if not isinstance(messages, list) or any(not isinstance(item, dict) for item in messages):
            raise SlackAPIError("expected Slack message objects")
        next_cursor = metadata.get("next_cursor") if isinstance(metadata, dict) else None
        if payload.get("has_more") is True and not next_cursor:
            raise SlackAPIError("Slack indicated more messages without returning a cursor")
        return Page(tuple(messages), next_cursor if isinstance(next_cursor, str) and next_cursor else None)
