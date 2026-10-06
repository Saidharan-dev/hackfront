import json
import sys
import unittest
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

SRC = Path(__file__).resolve().parents[2] / "src"
sys.path.insert(0, str(SRC))
FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "sources" / "slack"

from engineering_memory_ingestion.contracts import RecordKind, RelationshipKind  # noqa: E402
from engineering_memory_ingestion.sources.slack import HTTPResponse, SlackAdapter, SlackAPIError, SlackClient  # noqa: E402


def fixture(name):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


class FakeTransport:
    def __init__(self):
        self.calls = []
        self.payload = fixture("conversations_replies.json")

    def get(self, url, headers, timeout):
        self.calls.append((url, dict(headers), timeout))
        return HTTPResponse(200, {}, json.dumps(self.payload).encode())


class SlackAdapterTests(unittest.TestCase):
    def setUp(self):
        self.transport = FakeTransport()
        self.client = SlackClient("xoxb-secret", transport=self.transport)
        self.adapter = SlackAdapter(self.client)

    def test_thread_root_and_messages_preserve_native_relationships(self):
        page = self.adapter.thread_page("T_EXAMPLE", "C_EXAMPLE", "1789237500.000100")
        root, first_reply, second_reply = page.items
        self.assertEqual(root.kind, RecordKind.DISCUSSION_THREAD)
        self.assertEqual(root.source.source_id, "1789237500.000100")
        self.assertEqual(root.event_time, "2026-09-12T18:25:00.000100Z")
        self.assertEqual(first_reply.kind, RecordKind.DISCUSSION_MESSAGE)
        self.assertEqual(first_reply.references[0].relationship, RelationshipKind.REPLIES_TO)
        self.assertEqual(first_reply.references[0].target.source_id, root.source.source_id)
        self.assertIn("ENG-421", first_reply.text)
        self.assertIn("/api/conversations.replies?", root.provenance.source_uri)
        self.assertIsNone(page.next_cursor)

    def test_cursor_and_credentials_are_sent_to_slack_api(self):
        self.adapter.thread_page("T_EXAMPLE", "C_EXAMPLE", "1789237500.000100", cursor="page-2")
        url, headers, _ = self.transport.calls[0]
        self.assertEqual(urlsplit(url).path, "/api/conversations.replies")
        self.assertEqual(parse_qs(urlsplit(url).query)["cursor"], ["page-2"])
        self.assertEqual(headers["Authorization"], "Bearer xoxb-secret")
        self.assertNotIn("xoxb-secret", url)

    def test_next_cursor_is_returned_unchanged(self):
        self.transport.payload["response_metadata"]["next_cursor"] = "next-opaque-token"
        page = self.adapter.thread_page("T_EXAMPLE", "C_EXAMPLE", "1789237500.000100")
        self.assertEqual(page.next_cursor, "next-opaque-token")

    def test_page_limit_and_provider_errors_are_checked(self):
        with self.assertRaisesRegex(ValueError, "between 1 and 15"):
            self.adapter.thread_page("T_EXAMPLE", "C_EXAMPLE", "1789237500.000100", limit=16)
        self.transport.payload = {"ok": False, "error": "invalid_auth"}
        with self.assertRaises(SlackAPIError):
            self.adapter.thread_page("T_EXAMPLE", "C_EXAMPLE", "1789237500.000100")


if __name__ == "__main__":
    unittest.main()
