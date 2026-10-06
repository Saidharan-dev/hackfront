import json
import sys
import unittest
from dataclasses import replace
from pathlib import Path

SRC = Path(__file__).resolve().parents[2] / "src"
sys.path.insert(0, str(SRC))
FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "sources"

from engineering_memory_ingestion.extraction import EXTRACTION_VERSION, extract_deterministic  # noqa: E402
from engineering_memory_ingestion.sources.github.mapper import map_commit, map_pull_request, map_pull_request_activity  # noqa: E402
from engineering_memory_ingestion.sources.jira.mapper import map_issue  # noqa: E402
from engineering_memory_ingestion.sources.slack.mapper import map_thread_message  # noqa: E402


def fixture(path):
    return json.loads((FIXTURES / path).read_text(encoding="utf-8"))


class DeterministicExtractionTests(unittest.TestCase):
    def test_git_commit_extracts_ids_times_paths_stats_and_parent_reference(self):
        payload = fixture("github/commit_detail.json")
        artifact = map_commit(payload, "acme", "payments")
        result = extract_deterministic(artifact)
        self.assertEqual(result.canonical_id, artifact.canonical_id)
        self.assertEqual(result.values_for("source_id")[0].locator, "$.sha")
        self.assertEqual(result.values_for("event_time")[0].locator, "$.commit.author.date")
        self.assertEqual(result.values_for("path")[0].locator, "$.files[0].filename")
        self.assertEqual(result.values_for("additions")[0].locator, "$.stats.additions")
        self.assertEqual(result.values_for("reference")[0].locator, "$.parents[0].sha")
        self.assertEqual(result.values_for("diff")[0].value, payload["files"][0]["patch"])
        self.assertEqual(result.values_for("diff")[0].locator, "$.files[0].patch")
        self.assertTrue(all(value.extraction_version == EXTRACTION_VERSION for value in result.values))

    def test_pull_request_keeps_explicit_commit_refs_and_does_not_extract_meaning(self):
        artifact = map_pull_request(fixture("github/pull_request.json"), "acme", "payments")
        result = extract_deterministic(artifact)
        self.assertEqual(result.values_for("event_time")[0].locator, "$.created_at")
        self.assertEqual(len(result.values_for("reference")), len(artifact.references))
        self.assertFalse({"text", "title", "semantic_summary"} & {value.field for value in result.values})

        payload = fixture("github/pull_request_review_comments.json")[0]
        comment = map_pull_request_activity(payload, "acme", "payments", 482, "review_comments")
        extracted = extract_deterministic(comment).values_for("diff")
        self.assertEqual(extracted[0].value, payload["diff_hunk"])
        self.assertEqual(extracted[0].locator, "$.diff_hunk")

    def test_jira_and_slack_values_have_native_locators(self):
        issue = map_issue(fixture("jira/issue.json"), "https://acme.atlassian.net")
        issue_result = extract_deterministic(issue)
        self.assertEqual(issue_result.values_for("source_id")[0].locator, "$.key")
        self.assertEqual(issue_result.values_for("event_time")[0].locator, "$.fields.created")
        self.assertEqual(issue_result.values_for("reference")[0].locator, "$.fields.issuelinks[0]")

        shifted = replace(issue, event_time="2026-09-11T23:30:00-05:30")
        self.assertEqual(
            extract_deterministic(shifted).values_for("event_time")[0].value,
            "2026-09-12T05:00:00Z",
        )

        thread = fixture("slack/conversations_replies.json")["messages"][0]
        thread_artifact = map_thread_message(thread, "T_EXAMPLE", "C_EXAMPLE", thread["thread_ts"])
        slack_result = extract_deterministic(thread_artifact)
        self.assertEqual(slack_result.values_for("source_id")[0].locator, "$.ts")
        self.assertEqual(slack_result.values_for("event_time")[0].locator, "$.ts")
        self.assertEqual(slack_result.values_for("provenance")[0].value, thread_artifact.provenance)


if __name__ == "__main__":
    unittest.main()
