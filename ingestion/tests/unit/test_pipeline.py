import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
FIXTURES = ROOT / "tests" / "fixtures" / "sources"

from engineering_memory_ingestion.contracts import SCHEMA_VERSION  # noqa: E402
from engineering_memory_ingestion.core import run_ingestion  # noqa: E402
from engineering_memory_ingestion.extraction import EXTRACTION_VERSION  # noqa: E402
from engineering_memory_ingestion.sources.github.mapper import map_commit, map_pull_request  # noqa: E402
from engineering_memory_ingestion.sources.jira.mapper import map_comment, map_issue  # noqa: E402
from engineering_memory_ingestion.sources.slack.mapper import map_thread_message  # noqa: E402


def fixture(name):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def fixture_artifacts():
    slack_messages = fixture("slack/conversations_replies.json")["messages"]
    return (
        map_commit(fixture("github/commit_detail.json"), "acme", "payments"),
        map_pull_request(fixture("github/pull_request.json"), "acme", "payments"),
        map_issue(fixture("jira/issue.json"), "https://acme.atlassian.net"),
        map_comment(
            fixture("jira/issue_comments.json")["comments"][0],
            "https://acme.atlassian.net", "ENG", "ENG-421",
        ),
        *(map_thread_message(message, "T_EXAMPLE", "C_EXAMPLE", slack_messages[0]["ts"])
          for message in slack_messages),
    )


class MemoryStore:
    """Idempotent graph-writer double keyed by the canonical artifact ID."""

    def __init__(self):
        self.artifacts = {}
        self.references = set()

    def write_artifact(self, artifact):
        self.artifacts[artifact.canonical_id] = artifact
        self.references.update(
            (artifact.canonical_id, reference.relationship.value, reference.target.canonical_id)
            for reference in artifact.references
        )
        return artifact.canonical_id


class IngestionPipelineTests(unittest.TestCase):
    def test_bounded_fixture_replay_resumes_and_keeps_graph_records_idempotent(self):
        artifacts = fixture_artifacts()
        cursor_secret = "opaque-cursor-secret-do-not-log"

        def fetch(cursor):
            if cursor is None:
                return type("Page", (), {"items": artifacts[:3], "next_cursor": cursor_secret})()
            if cursor == cursor_secret:
                return type("Page", (), {"items": artifacts[3:], "next_cursor": None})()
            raise AssertionError("unexpected cursor")

        store = MemoryStore()
        first = run_ingestion(
            source="fixture-bundle", fetch_page=fetch, writer=store, max_pages=1, adapter_version="fixtures/1"
        )
        self.assertFalse(first.summary.complete)
        self.assertEqual(first.resume_cursor, cursor_secret)
        self.assertEqual(first.summary.persisted_count, 3)
        self.assertEqual(first.summary.schema_version, SCHEMA_VERSION)
        self.assertEqual(first.summary.extraction_version, EXTRACTION_VERSION)

        # Replaying the first page is safe; resuming then persists the remainder.
        replay = run_ingestion(source="fixture-bundle", fetch_page=fetch, writer=store, max_pages=1)
        resumed = run_ingestion(
            source="fixture-bundle", fetch_page=fetch, writer=store, cursor=first.resume_cursor
        )
        self.assertTrue(resumed.summary.complete)
        self.assertEqual(len(store.artifacts), len(artifacts))
        self.assertGreaterEqual(len(store.references), 4)
        self.assertEqual(replay.summary.persisted_count, 3)
        self.assertEqual(resumed.summary.persisted_count, len(artifacts) - 3)
        self.assertIsNotNone(resumed.summary.source_time_min)
        self.assertIsNotNone(resumed.summary.source_time_max)
        self.assertNotIn(cursor_secret, first.summary.to_json())
        self.assertNotIn("access token refresh failed", first.summary.to_json())

    def test_page_failure_is_safe_and_keeps_cursor_for_replay(self):
        secret_cursor = "sensitive-provider-cursor"

        def fail(_cursor):
            raise RuntimeError(f"access_token=do-not-report {secret_cursor} private message body")

        result = run_ingestion(
            source="slack", fetch_page=fail, writer=MemoryStore(), cursor=secret_cursor, max_pages=2
        )
        output = result.summary.to_json()
        self.assertEqual(result.resume_cursor, secret_cursor)
        self.assertFalse(result.summary.complete)
        self.assertEqual(result.summary.errors[0].stage, "fetch_or_normalize")
        for value in (secret_cursor, "do-not-report", "private message body"):
            self.assertNotIn(value, output)

    def test_partial_persistence_replays_the_failed_page(self):
        artifacts = fixture_artifacts()
        start_cursor = "starting-cursor"

        class FailOnSecondWrite(MemoryStore):
            def __init__(self):
                super().__init__()
                self.calls = 0

            def write_artifact(self, artifact):
                self.calls += 1
                if self.calls == 2:
                    raise RuntimeError("credential and source text must not escape")
                return super().write_artifact(artifact)

        page = type("Page", (), {"items": artifacts[:2], "next_cursor": "later-page"})()
        store = FailOnSecondWrite()
        result = run_ingestion(
            source="github", fetch_page=lambda _: page, writer=store, cursor=start_cursor, max_pages=1
        )
        self.assertEqual(result.resume_cursor, start_cursor)
        self.assertEqual(result.summary.persisted_count, 1)
        self.assertEqual(result.summary.errors[0].stage, "persist")
        self.assertNotIn("credential", result.summary.to_json())

    def test_requires_a_positive_page_bound(self):
        with self.assertRaisesRegex(ValueError, "max_pages"):
            run_ingestion(source="github", fetch_page=lambda _: None, writer=MemoryStore(), max_pages=0)


if __name__ == "__main__":
    unittest.main()
