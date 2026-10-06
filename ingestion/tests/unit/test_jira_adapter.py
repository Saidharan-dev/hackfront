import json
import sys
import unittest
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

SRC = Path(__file__).resolve().parents[2] / "src"
sys.path.insert(0, str(SRC))
FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "sources" / "jira"

from engineering_memory_ingestion.contracts import RecordKind, RelationshipKind  # noqa: E402
from engineering_memory_ingestion.sources.jira import HTTPResponse, JiraAdapter, JiraClient  # noqa: E402


def fixture(name):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


class FakeTransport:
    def __init__(self):
        self.calls = []
        self.issue = fixture("issue.json")
        self.comments = fixture("issue_comments.json")

    def get(self, url, headers, timeout):
        self.calls.append((url, dict(headers), timeout))
        if "/comment?" in url:
            query = parse_qs(urlsplit(url).query)
            start = int(query.get("startAt", ["0"])[0])
            size = int(query.get("maxResults", ["100"])[0])
            payload = dict(self.comments)
            payload["startAt"] = start
            payload["maxResults"] = size
            payload["comments"] = self.comments["comments"][start : start + size]
            return HTTPResponse(200, {}, json.dumps(payload).encode())
        return HTTPResponse(200, {}, json.dumps(self.issue).encode())


class JiraAdapterTests(unittest.TestCase):
    def setUp(self):
        self.transport = FakeTransport()
        self.client = JiraClient(
            "https://acme.atlassian.net", "api-secret", email="ingester@example.invalid", transport=self.transport
        )
        self.adapter = JiraAdapter(self.client, "https://acme.atlassian.net")

    def test_issue_maps_native_fields_and_explicit_issue_links(self):
        record = self.adapter.issue("ENG-421")
        self.assertEqual(record.kind, RecordKind.ISSUE)
        self.assertEqual(record.source.source_id, "ENG-421")
        self.assertEqual(record.title, "Prevent duplicate charges from repeated payment attempts")
        self.assertEqual(record.text, "Payment retries sometimes create duplicate charges when the provider responds slowly.")
        self.assertEqual(record.event_time, "2026-09-11T18:00:00Z")
        self.assertEqual(record.actor.source_id, "acct-example-001")
        self.assertEqual(record.context["status"], "Done")
        self.assertEqual(record.references[0].target.source_id, "ENG-482")
        self.assertEqual(record.references[0].relationship, RelationshipKind.REFERENCES)
        self.assertEqual(record.raw_payload["key"], "ENG-421")

    def test_comments_are_paginated_and_link_back_to_issue(self):
        page = self.adapter.comments_page("ENG-421", per_page=1)
        comment = page.items[0]
        self.assertEqual(comment.kind, RecordKind.DISCUSSION_MESSAGE)
        self.assertIn("provider response arrives", comment.text)
        self.assertEqual(comment.references[0].target.source_id, "ENG-421")
        self.assertIsNotNone(page.next_cursor)
        query = parse_qs(urlsplit(self.transport.calls[-1][0]).query)
        self.assertEqual(query["maxResults"], ["1"])
        next_page = self.adapter.comments_page("ENG-421", cursor=page.next_cursor, per_page=1)
        self.assertEqual(next_page.items[0].source.source_id, "300422")
        self.assertIsNone(next_page.next_cursor)

    def test_credentials_use_authorization_header(self):
        self.adapter.issue("ENG-421")
        _, headers, _ = self.transport.calls[0]
        self.assertTrue(headers["Authorization"].startswith("Basic "))
        self.assertNotIn("api-secret", self.transport.calls[0][0])


if __name__ == "__main__":
    unittest.main()
