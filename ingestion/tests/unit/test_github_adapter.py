import copy
import json
import sys
import unittest
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

SRC = Path(__file__).resolve().parents[2] / "src"
sys.path.insert(0, str(SRC))
FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "sources" / "github"

from engineering_memory_ingestion.contracts import RecordKind, RelationshipKind  # noqa: E402
from engineering_memory_ingestion.sources.github import (  # noqa: E402
    GitHubAPIError,
    GitHubAdapter,
    GitHubClient,
    HTTPResponse,
)


def fixture(name):
    with (FIXTURES / name).open(encoding="utf-8-sig") as stream:
        return json.load(stream)


class FakeTransport:
    def __init__(self):
        self.calls = []
        self.commit = fixture("commit_detail.json")
        self.pull = fixture("pull_request.json")
        self.reviews = fixture("pull_request_reviews.json")
        self.review_comments = fixture("pull_request_review_comments.json")
        self.issue_comments = fixture("pull_request_issue_comments.json")

    def get(self, url, headers, timeout):
        self.calls.append((url, dict(headers), timeout))
        path = urlsplit(url).path
        query = parse_qs(urlsplit(url).query)
        if path.endswith("/pulls"):
            return HTTPResponse(200, {}, json.dumps([self.pull]).encode())
        if path.endswith("/pulls/482/reviews"):
            return HTTPResponse(200, {}, json.dumps(self.reviews).encode())
        if path.endswith("/pulls/482/comments"):
            return HTTPResponse(200, {}, json.dumps(self.review_comments).encode())
        if path.endswith("/issues/482/comments"):
            return HTTPResponse(200, {}, json.dumps(self.issue_comments).encode())
        if path.endswith("/commits"):
            page = query.get("page", ["1"])[0]
            if page == "2":
                return HTTPResponse(200, {}, b"[]")
            summary = copy.deepcopy(self.commit)
            summary.pop("files")
            summary.pop("stats")
            next_url = "https://api.github.com/repos/acme/payments/commits?per_page=1&page=2"
            headers = {"Link": f'<{next_url}>; rel="next", <https://api.github.com/repos/acme/payments/commits?per_page=1&page=3>; rel="last"'}
            return HTTPResponse(200, headers, json.dumps([summary]).encode())
        if path.endswith("/" + self.commit["sha"]):
            return HTTPResponse(200, {}, json.dumps(self.commit).encode())
        return HTTPResponse(404, {}, b'{"message":"not found"}')


class GitHubAdapterTests(unittest.TestCase):
    def setUp(self):
        self.transport = FakeTransport()
        self.client = GitHubClient("secret-token", transport=self.transport)
        self.adapter = GitHubAdapter(self.client)

    def test_commit_page_fetches_details_and_maps_native_history(self):
        page = self.adapter.commits_page("acme", "payments", per_page=1, since="2026-01-01T00:00:00Z")
        record = page.items[0]
        self.assertEqual(record.kind, RecordKind.GIT_COMMIT)
        self.assertEqual(record.source.source_id, "a1b2c3d4e5f6789012345678901234567890abcd")
        self.assertEqual(record.event_time, "2026-09-12T14:20:00Z")
        self.assertEqual(record.change.paths, ("src/payments/retry.py",))
        self.assertEqual(record.change.additions, 1)
        self.assertEqual(record.change.deletions, 1)
        self.assertEqual(record.references[0].target.source_id, "fedcba0987654321098765432109876543210fed")
        self.assertEqual(record.raw_payload["sha"], record.source.source_id)
        self.assertIsNotNone(page.next_cursor)

    def test_saved_cursor_fetches_next_page_without_reapplying_initial_filters(self):
        first = self.adapter.commits_page("acme", "payments", per_page=1, since="2026-01-01T00:00:00Z")
        second = self.adapter.commits_page(
            "acme", "payments", cursor=first.next_cursor, since="2026-01-01T00:00:00Z"
        )
        self.assertEqual(second.items, ())
        self.assertIsNone(second.next_cursor)
        self.assertTrue(urlsplit(self.transport.calls[-1][0]).query.endswith("page=2"))

    def test_pull_request_maps_to_the_head_commit(self):
        page = self.adapter.pull_requests_page("acme", "payments", per_page=1)
        record = page.items[0]
        self.assertEqual(record.kind, RecordKind.PULL_REQUEST)
        self.assertEqual(record.source.source_id, "482")
        self.assertEqual(record.context["merged"], True)
        head_link = next(ref for ref in record.references if ref.locator == "$.head.sha")
        self.assertEqual(head_link.relationship, RelationshipKind.CONTAINS)
        self.assertEqual(head_link.target.source_id, self.transport.pull["head"]["sha"])
        self.assertIn("ENG-421", record.text)

    def test_reviews_map_state_and_submission_time(self):
        record = self.adapter.pull_request_reviews_page("acme", "payments", 482).items[0]
        self.assertEqual(record.kind, RecordKind.DISCUSSION_MESSAGE)
        self.assertEqual(record.title, "Review: APPROVED")
        self.assertEqual(record.event_time, "2026-09-12T14:50:00Z")
        self.assertEqual(record.context["state"], "APPROVED")

    def test_review_comments_preserve_diff_and_reply_relationship(self):
        records = self.adapter.pull_request_review_comments_page("acme", "payments", 482).items
        self.assertEqual(records[0].text, self.transport.review_comments[0]["body"])
        self.assertEqual(records[0].change.paths, ("src/payments/retry.py",))
        self.assertIn("diff_hunk", records[0].context)
        reply = next(ref for ref in records[1].references if ref.relationship == RelationshipKind.REPLIES_TO)
        self.assertEqual(reply.target.source_id, "94101")
        self.assertTrue(self.transport.calls[-1][0].endswith("/pulls/482/comments?per_page=100"))

    def test_issue_comments_link_to_pull_request(self):
        record = self.adapter.pull_request_issue_comments_page("acme", "payments", 482).items[0]
        self.assertEqual(record.text, self.transport.issue_comments[0]["body"])
        self.assertEqual(record.references[0].target.source_id, "482")

    def test_credentials_are_headers_and_not_part_of_cursor_or_error_text(self):
        self.adapter.pull_requests_page("acme", "payments")
        _, headers, _ = self.transport.calls[0]
        self.assertEqual(headers["Authorization"], "Bearer secret-token")
        self.assertNotIn("secret-token", self.transport.calls[0][0])

    def test_rejects_cross_origin_cursor_before_request(self):
        before = len(self.transport.calls)
        with self.assertRaisesRegex(ValueError, "stay under this host"):
            self.client.get_page(
                "repos/acme/payments/commits",
                cursor="https://attacker.example/repos/acme/payments/commits?page=2",
            )
        self.assertEqual(len(self.transport.calls), before)

    def test_page_size_is_bounded_by_provider_limit(self):
        with self.assertRaisesRegex(ValueError, "between 1 and 100"):
            self.adapter.commits_page("acme", "payments", per_page=101)


if __name__ == "__main__":
    unittest.main()
