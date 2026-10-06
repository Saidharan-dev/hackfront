"""Idempotent persistence for canonical artifacts and their explicit references."""

from __future__ import annotations

import hashlib
import json
import os
from typing import Any

from ...contracts import Artifact
from .schema import initialize_schema


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _node_properties(artifact: Artifact) -> dict[str, Any]:
    properties: dict[str, Any] = {
        "canonical_id": artifact.canonical_id,
        "provider": artifact.source.provider,
        "workspace": artifact.source.workspace,
        "source_record_type": artifact.source.record_type,
        "source_id": artifact.source.source_id,
        "record_kind": artifact.kind.value,
        "schema_version": artifact.schema_version,
        "observed_at": artifact.observed_at,
        "context_json": _json(dict(artifact.context)),
        "raw_payload_json": _json(dict(artifact.raw_payload)) if artifact.raw_payload is not None else None,
        "provenance_source_uri": artifact.provenance.source_uri,
        "provenance_locator": artifact.provenance.locator,
        "provenance_adapter_version": artifact.provenance.adapter_version,
        "provenance_payload_uri": artifact.provenance.payload_uri,
        "provenance_payload_sha256": artifact.provenance.payload_sha256,
        "is_stub": False,
    }
    optional = {
        "source_uri": artifact.source.uri,
        "event_time": artifact.event_time,
        "updated_at": artifact.updated_at,
        "title": artifact.title,
        "text": artifact.text,
    }
    properties.update({key: value for key, value in optional.items() if value is not None})
    if artifact.actor:
        properties.update({
            "actor_provider": artifact.actor.provider,
            "actor_source_id": artifact.actor.source_id,
            "actor_display_name": artifact.actor.display_name,
            "actor_handle": artifact.actor.handle,
        })
    if artifact.change:
        properties["change_paths"] = list(artifact.change.paths)
        for name in ("additions", "deletions", "before", "after"):
            value = getattr(artifact.change, name)
            if value is not None:
                properties[f"change_{name}"] = value
    return properties


def _stub_properties(identity) -> dict[str, Any]:
    properties = {
        "canonical_id": identity.canonical_id,
        "provider": identity.provider,
        "workspace": identity.workspace,
        "source_record_type": identity.record_type,
        "source_id": identity.source_id,
        "is_stub": True,
    }
    if identity.uri:
        properties["source_uri"] = identity.uri
    return properties


def _reference_id(source_id: str, kind: str, target_id: str, locator: str) -> str:
    material = "\0".join((source_id, kind, target_id, locator))
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def _write_artifact_tx(tx, artifact: Artifact, properties: dict[str, Any]) -> None:
    tx.run(
        "MERGE (artifact:Artifact {canonical_id: $canonical_id}) SET artifact += $properties",
        canonical_id=artifact.canonical_id,
        properties=properties,
    ).consume()
    for reference in artifact.references:
        # RelationshipKind is a closed enum, so this identifier cannot contain Cypher syntax.
        kind = reference.relationship.value
        relationship_id = _reference_id(
            artifact.canonical_id, kind, reference.target.canonical_id, reference.locator
        )
        query = f"""
        MATCH (source:Artifact {{canonical_id: $source_id}})
        MERGE (target:Artifact {{canonical_id: $target_id}})
        ON CREATE SET target += $target_properties
        MERGE (source)-[edge:{kind} {{canonical_id: $relationship_id}}]->(target)
        SET edge.kind = $kind,
            edge.locator = $locator,
            edge.source_uri = $source_uri,
            edge.observed_at = $observed_at,
            edge.adapter_version = $adapter_version
        """
        tx.run(
            query,
            source_id=artifact.canonical_id,
            target_id=reference.target.canonical_id,
            target_properties=_stub_properties(reference.target),
            relationship_id=relationship_id,
            kind=kind,
            locator=reference.locator,
            source_uri=artifact.provenance.source_uri,
            observed_at=artifact.observed_at,
            adapter_version=artifact.provenance.adapter_version,
        ).consume()


class Neo4jStore:
    """Own one driver and use managed transactions for stable, retry-safe writes."""

    def __init__(self, driver, database: str = "neo4j"):
        if not database:
            raise ValueError("database is required")
        self.driver = driver
        self.database = database

    @classmethod
    def from_environment(cls) -> "Neo4jStore":
        uri = os.environ.get("NEO4J_URI")
        username = os.environ.get("NEO4J_USERNAME")
        password = os.environ.get("NEO4J_PASSWORD")
        if not all((uri, username, password)):
            raise ValueError("NEO4J_URI, NEO4J_USERNAME, and NEO4J_PASSWORD must be configured")
        try:
            from neo4j import GraphDatabase
        except ImportError as error:
            raise RuntimeError("install the Neo4j Python driver to use Neo4jStore") from error
        driver = GraphDatabase.driver(uri, auth=(username, password))
        driver.verify_connectivity()
        return cls(driver, os.environ.get("NEO4J_DATABASE", "neo4j"))

    def initialize_schema(self) -> None:
        initialize_schema(self.driver, self.database)

    def write_artifact(self, artifact: Artifact) -> str:
        if not isinstance(artifact, Artifact):
            raise TypeError("write_artifact requires an Artifact")
        with self.driver.session(database=self.database) as session:
            session.execute_write(_write_artifact_tx, artifact, _node_properties(artifact))
        return artifact.canonical_id

    def write_many(self, artifacts) -> tuple[str, ...]:
        return tuple(self.write_artifact(artifact) for artifact in artifacts)

    def close(self) -> None:
        self.driver.close()

    def __enter__(self) -> "Neo4jStore":
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        self.close()
