"""Neo4j constraints for durable canonical nodes and source relationships."""

from ...contracts import RelationshipKind

ARTIFACT_ID_CONSTRAINT = (
    "CREATE CONSTRAINT artifact_canonical_id IF NOT EXISTS "
    "FOR (artifact:Artifact) REQUIRE artifact.canonical_id IS UNIQUE"
)
RELATIONSHIP_ID_CONSTRAINTS = tuple(
    f"CREATE CONSTRAINT relationship_{kind.value.lower()}_canonical_id IF NOT EXISTS "
    f"FOR ()-[relationship:{kind.value}]-() REQUIRE relationship.canonical_id IS UNIQUE"
    for kind in RelationshipKind
)


def initialize_schema(driver, database: str = "neo4j") -> None:
    with driver.session(database=database) as session:
        session.run(ARTIFACT_ID_CONSTRAINT).consume()
        for constraint in RELATIONSHIP_ID_CONSTRAINTS:
            session.run(constraint).consume()
