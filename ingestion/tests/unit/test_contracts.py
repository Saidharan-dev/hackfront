import sys
import unittest
from pathlib import Path

SRC = Path(__file__).resolve().parents[2] / "src"
sys.path.insert(0, str(SRC))

from engineering_memory_ingestion.contracts import (  # noqa: E402
    Actor,
    Artifact,
    Change,
    Provenance,
    RecordKind,
    RelationshipKind,
    SourceIdentity,
    SourceReference,
)


class ContractTests(unittest.TestCase):
    def setUp(self):
        self.source = SourceIdentity("github", "acme/payments", "commit", "abc:123")
        self.provenance = Provenance(
            source_uri="https://api.github.com/repos/acme/payments/commits/abc",
            locator="$.commit.message",
            observed_at="2026-09-12T15:00:00Z",
            adapter_version="github-adapter/0.1",
            payload_sha256="a" * 64,
        )

    def test_canonical_identity_is_namespaced_and_escapes_delimiters(self):
        self.assertEqual(
            self.source.canonical_id,
            "github:acme%2Fpayments:commit:abc%3A123",
        )

    def test_artifact_keeps_source_evidence_and_explicit_reference(self):
        issue = SourceIdentity("jira", "acme", "issue", "ENG-421")
        record = Artifact(
            source=self.source,
            kind=RecordKind.GIT_COMMIT,
            observed_at="2026-09-12T15:00:00+00:00",
            event_time="2026-09-12T14:20:00Z",
            actor=Actor("github", "10001", "Morgan Example", "morgan-example"),
            provenance=self.provenance,
            references=(
                SourceReference(issue, RelationshipKind.REFERENCES, "$.commit.message"),
            ),
            change=Change(paths=("src/payments/retry.py",), additions=1, deletions=1),
            raw_payload={"sha": "abc"},
        )
        self.assertEqual(record.canonical_id, self.source.canonical_id)
        self.assertEqual(record.references[0].target, issue)
        self.assertEqual(record.raw_payload["sha"], "abc")

    def test_record_requires_raw_payload_or_durable_payload_reference(self):
        with self.assertRaisesRegex(ValueError, "raw_payload or provenance.payload_uri"):
            Artifact(
                source=self.source,
                kind=RecordKind.GIT_COMMIT,
                observed_at="2026-09-12T15:00:00Z",
                provenance=self.provenance,
            )

    def test_timestamps_require_timezone_offsets(self):
        with self.assertRaisesRegex(ValueError, "UTC offset"):
            Artifact(
                source=self.source,
                kind=RecordKind.GIT_COMMIT,
                observed_at="2026-09-12T15:00:00",
                provenance=self.provenance,
                raw_payload={"sha": "abc"},
            )

    def test_change_statistics_cannot_be_negative(self):
        with self.assertRaisesRegex(ValueError, "additions"):
            Change(additions=-1)


if __name__ == "__main__":
    unittest.main()
