"""Small Jira Cloud REST client with injectable transport and bounded pages."""

from __future__ import annotations

import base64
import json
import os
from dataclasses import dataclass
from typing import Mapping, Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urljoin, urlsplit, urlunsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener


MAX_PAGE_SIZE = 100


class JiraAPIError(RuntimeError):
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


def _origin(url: str) -> tuple[str, str, int | None]:
    parsed = urlsplit(url)
    return parsed.scheme.lower(), (parsed.hostname or "").lower(), parsed.port


class _SameOriginRedirect(HTTPRedirectHandler):
    def __init__(self, origin: tuple[str, str, int | None]):
        super().__init__()
        self.origin = origin

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if _origin(newurl) != self.origin:
            return None
        return super().redirect_request(req, fp, code, msg, headers, newurl)


class UrlLibTransport:
    def __init__(self, base_url: str):
        self.origin = _origin(base_url)

    def get(self, url: str, headers: Mapping[str, str], timeout: float) -> HTTPResponse:
        try:
            with build_opener(_SameOriginRedirect(self.origin)).open(
                Request(url, headers=dict(headers), method="GET"), timeout=timeout
            ) as response:
                return HTTPResponse(response.status, dict(response.headers.items()), response.read())
        except HTTPError as error:
            error.close()
            raise JiraAPIError(f"Jira API returned HTTP {error.code}", error.code) from None
        except URLError as error:
            raise JiraAPIError("Jira API transport failed") from None
        except TimeoutError:
            raise JiraAPIError("Jira API request timed out") from None


@dataclass(frozen=True, slots=True)
class Page:
    items: tuple[Mapping[str, object], ...]
    next_cursor: str | None


class JiraClient:
    def __init__(
        self,
        base_url: str,
        token: str | None = None,
        *,
        email: str | None = None,
        transport: Transport | None = None,
        timeout: float = 30.0,
    ):
        parsed = urlsplit(base_url.rstrip("/"))
        if parsed.scheme != "https" or not parsed.netloc or parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError("base_url must be an absolute HTTPS URL")
        self.base_url = base_url.rstrip("/")
        self.origin = _origin(self.base_url)
        self.base_path = parsed.path.rstrip("/")
        self.token = token
        self.email = email
        self.timeout = timeout
        self.transport = transport or UrlLibTransport(self.base_url)

    @classmethod
    def from_environment(cls, *, base_url: str, **kwargs) -> "JiraClient":
        return cls(
            base_url,
            os.environ.get("JIRA_API_TOKEN"),
            email=os.environ.get("JIRA_EMAIL"),
            **kwargs,
        )

    def _headers(self) -> dict[str, str]:
        headers = {"Accept": "application/json", "User-Agent": "engineering-memory-ingestion/0.1"}
        if self.token:
            value = f"{self.email}:{self.token}" if self.email else self.token
            scheme = "Basic " + base64.b64encode(value.encode()).decode() if self.email else "Bearer " + value
            headers["Authorization"] = scheme
        return headers

    def _validate_url(self, url: str) -> str:
        parsed = urlsplit(url)
        if (
            parsed.scheme != "https"
            or parsed.username
            or parsed.password
            or _origin(url) != self.origin
            or not parsed.path.startswith(f"{self.base_path}/rest/api/")
        ):
            raise ValueError("Jira URL must stay under this host's REST API")
        return url

    def _get_json(self, url: str) -> object:
        response = self.transport.get(self._validate_url(url), self._headers(), self.timeout)
        if not 200 <= response.status < 300:
            raise JiraAPIError(f"Jira API returned HTTP {response.status}", response.status)
        try:
            return json.loads(response.body)
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise JiraAPIError("Jira API returned invalid JSON", response.status) from None

    def get_issue(self, issue_key: str) -> Mapping[str, object]:
        if not issue_key or any(char in issue_key for char in "/?#"):
            raise ValueError("invalid issue key")
        fields = "summary,description,issuetype,project,status,priority,reporter,created,updated,labels,issuelinks"
        url = f"{self.base_url}/rest/api/3/issue/{issue_key}?{urlencode({'fields': fields})}"
        payload = self._get_json(url)
        if not isinstance(payload, dict):
            raise JiraAPIError("expected a JSON object for Jira issue")
        return payload

    def comments_page(self, issue_key: str, *, cursor: str | None = None, per_page: int = 100) -> Page:
        if not issue_key or any(char in issue_key for char in "/?#"):
            raise ValueError("invalid issue key")
        if not 1 <= per_page <= MAX_PAGE_SIZE:
            raise ValueError(f"per_page must be between 1 and {MAX_PAGE_SIZE}")
        if cursor:
            url = self._validate_url(cursor)
        else:
            query = urlencode({"startAt": 0, "maxResults": per_page})
            url = f"{self.base_url}/rest/api/3/issue/{issue_key}/comment?{query}"
        payload = self._get_json(url)
        if not isinstance(payload, dict) or not isinstance(payload.get("comments"), list):
            raise JiraAPIError("expected paginated Jira comments")
        comments = payload["comments"]
        if any(not isinstance(item, dict) for item in comments):
            raise JiraAPIError("expected Jira comment objects")
        start = payload.get("startAt", 0)
        total = payload.get("total", 0)
        next_cursor = None
        if isinstance(start, int) and isinstance(total, int) and start + len(comments) < total:
            if not comments:
                raise JiraAPIError("Jira returned an empty comment page before the end of the collection")
            query = urlencode({"startAt": start + len(comments), "maxResults": per_page})
            next_cursor = f"{self.base_url}/rest/api/3/issue/{issue_key}/comment?{query}"
        return Page(tuple(comments), next_cursor)
