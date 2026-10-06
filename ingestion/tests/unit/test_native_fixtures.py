import json
import unittest
from pathlib import Path

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "sources"


def load_fixture(*parts):
    with (FIXTURES.joinpath(*parts)).open(encoding="utf-8-sig") as stream:
        return json.load(stream)


class NativeFixtureShapeTests(unittest.TestCase):
    def test_github_commit_and_hosted_pull_request_are_linked_by_native_sha(self):
        commit = load_fixture("github", "commit_detail.json")
        pull = load_fixture("github", "pull_request.json")
        pull_commits = load_fixture("github", "pull_request_commits.json")

        self.assertIn("sha", commit)
        self.assertIn("commit", commit)
        self.assertIn("parents", commit)
        self.assertIn("files", commit)
        self.assertIn("patch", commit["files"][0])
        self.assertIn("head", pull)
        self.assertIn("base", pull)
        self.assertIn("merged_at", pull)
        self.assertIn("_links", pull)
        self.assertEqual(pull["head"]["sha"], commit["sha"])
        self.assertEqual(pull_commits[0]["sha"], commit["sha"])

    def test_jira_issue_fixture_uses_issue_rest_fields_and_link_envelopes(self):
        issue = load_fixture("jira", "issue.json")
        fields = issue["fields"]
        self.assertTrue(issue["key"].startswith("ENG-"))
        for field in ("project", "issuetype", "status", "created", "updated", "issuelinks", "comment"):
            self.assertIn(field, fields)
        self.assertIn("summary", fields)

    def test_slack_fixture_uses_web_api_thread_and_pagination_fields(self):
        response = load_fixture("slack", "conversations_replies.json")
        self.assertTrue(response["ok"])
        self.assertIn("response_metadata", response)
        parent, reply = response["messages"][:2]
        self.assertEqual(parent["ts"], parent["thread_ts"])
        self.assertEqual(reply["thread_ts"], parent["ts"])

    def test_fixtures_have_synthetic_non_routable_identity(self):
        issue = load_fixture("jira", "issue.json")
        self.assertTrue(issue["fields"]["reporter"]["accountId"].startswith("acct-example"))
        self.assertEqual(issue["fields"]["reporter"]["displayName"], "Taylor Example")


if __name__ == "__main__":
    unittest.main()
