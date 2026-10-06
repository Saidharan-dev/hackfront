import json
import os
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))
FIXTURES = ROOT / "tests" / "fixtures" / "sources"

from neo4j import GraphDatabase  # noqa: E402
from engineering_memory_ingestion.contracts import RecordKind  # noqa: E402
from engineering_memory_ingestion.sources.github.mapper import map_commit, map_pull_request  # noqa: E402
from engineering_memory_ingestion.sources.jira.mapper import map_comment, map_issue  # noqa: E402
from engineering_memory_ingestion.sources.slack.mapper import map_thread_message  # noqa: E402
from engineering_memory_ingestion.storage.neo4j import Neo4jStore  # noqa: E402


def fixture(path):
    return json.loads((FIXTURES / path).read_text(encoding="utf-8"))


def fixture_artifacts():
    github_commit = fixture("github/commit_detail.json")
    pull_request = fixture("github/pull_request.json")
    jira_issue = fixture("jira/issue.json")
    slack_response = fixture("slack/conversations_replies.json")
    messages = slack_response["messages"]
    return (
        map_commit(github_commit, "acme", "payments"),
        map_pull_request(pull_request, "acme", "payments"),
        map_issue(jira_issue, "https://acme.atlassian.net"),
        map_comment(
            fixture("jira/issue_comments.json")["comments"][0],
            "https://acme.atlassian.net", "ENG", "ENG-421",
        ),
        *(map_thread_message(message, "T_EXAMPLE", "C_EXAMPLE", messages[0]["ts"]) for message in messages),
    )


class Neo4jStoreIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.driver = GraphDatabase.driver(
            os.environ["NEO4J_URI"],
            auth=(os.environ["NEO4J_USERNAME"], os.environ["NEO4J_PASSWORD"]),
        )
        cls.store = Neo4jStore(cls.driver, os.environ.get("NEO4J_DATABASE", "neo4j"))
        cls.store.initialize_schema()

    @classmethod
    def tearDownClass(cls):
        with cls.driver.session(database=cls.store.database) as session:
            session.run("MATCH (artifact:Artifact) DETACH DELETE artifact").consume()
        cls.store.close()

    def setUp(self):
        with self.driver.session(database=self.store.database) as session:
            session.run("MATCH (artifact:Artifact) DETACH DELETE artifact").consume()

    def test_replays_source_fixtures_with_explicit_typed_relationships(self):
        artifacts = fixture_artifacts()
        self.assertTrue(any(item.kind == RecordKind.GIT_COMMIT for item in artifacts))
        written = self.store.write_many(artifacts)
        with self.driver.session(database=self.store.database) as session:
            counts = session.run(
                "MATCH (a:Artifact) RETURN count(a) AS nodes, "
                "count(CASE WHEN a.is_stub = false THEN 1 END) AS full_nodes"
            ).single()
            relationships = session.run(
                "MATCH ()-[r]->() RETURN collect(DISTINCT type(r)) AS types, count(r) AS total"
            ).single()
        self.assertGreaterEqual(counts["nodes"], len(artifacts))
        self.assertEqual(counts["full_nodes"], len(artifacts))
        self.assertEqual(len(written), len(artifacts))
        self.assertTrue({"CONTAINS", "REFERENCES", "REPLIES_TO"}.issubset(set(relationships["types"])))
        self.assertGreaterEqual(relationships["total"], 4)

    def test_replaying_same_artifacts_is_idempotent_for_nodes_and_edges(self):
        artifacts = fixture_artifacts()
        self.store.write_many(artifacts)
        self.store.write_many(artifacts)
        with self.driver.session(database=self.store.database) as session:
            nodes = session.run("MATCH (a:Artifact) RETURN count(a) AS count").single()["count"]
            edge_ids = session.run(
                "MATCH ()-[r]->() RETURN count(r) AS count, count(DISTINCT r.canonical_id) AS ids"
            ).single()
        self.assertEqual(nodes, len(set(item.canonical_id for item in artifacts)) + 3)
        self.assertEqual(edge_ids["count"], edge_ids["ids"])


if __name__ == "__main__":
    unittest.main()
