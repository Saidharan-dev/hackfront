# Product specification — Engineering Memory Ingestion

> Status: draft. A coding agent must not implement product code until this specification is approved through Genesis.

## Problem

Engineering rationale is scattered across source repositories, issue trackers, pull requests, and team discussions. The ingestion layer must fetch or replay those source artifacts, preserve their native evidence and provenance, and normalize them into a technology-neutral contract that can be stored and traversed in Neo4j. The scope of this slice ends at durable graph ingestion; it does not generate “why” answers.

## Users

- Engineers investigating why code changed or which artifacts document a decision.
- The application’s later relationship-retrieval and reasoning components, which consume normalized, provenance-backed records.
- Developers running the ingestion pipeline locally against source-faithful mock datasets.

## Functional requirements

- FR-1: Provide independently replaceable Python adapters that ingest both Git history and hosted pull-request metadata, plus Jira issues and Slack discussions. Git history includes commit identity/parents, author and event time, message, refs, changed paths, and diffs or change statistics where available. Hosted pull-request data includes native ID/URL, title/body, author/times, merge state, source/target refs, reviews/comments, and links where available. Each adapter exposes pagination/cursor progress without leaking provider models into the core ingestion contract.
- FR-2: Normalize fetched artifacts into a versioned, source-neutral record envelope with canonical identity, source identity, record kind, actor, event/observation times, content, context, references, and provenance. Preserve the original native payload or a durable reference to it.
- FR-3: Perform deterministic extraction for source IDs, URLs, timestamps, repository/file paths, diffs/change metadata, and explicit cross-references. Every extracted value records its source locator and extraction version.
- FR-4: Persist records and explicit, typed source relationships into Neo4j using stable identifiers and idempotent upserts. Capture source, observed time, event/valid time where available, and provenance on stored records/edges.
- FR-5: Provide local mock source datasets whose JSON envelopes and fields match the selected platforms’ native API response shapes, and source clients that can replay those datasets without credentials or network access.
- FR-6: Support a bounded full backfill and cursor-based incremental replay for each adapter; retries of the same source item must not create duplicate nodes or edges.
- FR-7: Keep semantic extraction behind a separately configurable boundary. It must be disabled by default until its model, output schema, evidence requirements, and cost/privacy policy are approved.
- FR-8: Provide structured ingestion-run results with source, cursor range, fetched/normalized/persisted counts, errors, and adapter/schema versions; do not log secrets or raw sensitive content.

## Non-functional requirements

- NFR-1: Core schema, pipeline orchestration, and graph mapping depend on the canonical contract rather than a provider SDK or vendor-native data model.
- NFR-2: Local fixture runs need no provider credentials, external network, or pre-existing source accounts.
- NFR-3: Graph writes are idempotent and source records can be reprocessed from fixtures or retained raw payloads.
- NFR-4: Credentials are read from environment/configuration outside committed fixtures; mock data contains no real secrets or personal message content.
- NFR-5: The Neo4j connection is configurable by URI/database/user/password and can target a local development/test instance.

## Constraints

- Python is the implementation language.
- Neo4j is the graph persistence target; use its official Python driver at the persistence boundary.
- Keep the canonical schema, core ingestion pipeline, source adapters, Neo4j persistence, and mock data in separate, clearly named packages/directories.
- First slice must include Git history and hosted pull-request metadata, plus Jira and Slack fixtures/adapters as described in FR-1. GitHub is the provisional hosted provider based on the supplied repository context; the Git history acquisition route remains to be confirmed.

## Non-goals

- Answer generation, agent orchestration, retrieval ranking, evidence synthesis, or user interface.
- Vector database, embeddings, semantic relationship resolution, or automatic causal claims.
- Production-grade OAuth/onboarding, enterprise multi-tenant deployment, or large-scale distributed queues.
- Full source coverage for every Git host, issue tracker, and chat platform.
- Turning inferred semantic claims into authoritative facts.

## Acceptance criteria

- AC-1: A clean local setup can replay representative source-native fixture payloads into canonical records and persist those records and explicit references to a disposable Neo4j database without contacting external services.
- AC-2: Fixtures demonstrate a Git commit/change, its hosted pull request, one linked issue, and one threaded discussion; each normalized record can be traced to a native source ID and locator, and the commit-to-pull-request relationship is retained when supported by the source.
- AC-3: Replaying the same fixture batch twice produces the same logical graph entities and relationships, with no duplicate records.
- AC-4: Cursor progress, source timestamps, extraction/schema versions, and ingestion failures are inspectable in run output; sensitive values and credentials are not written to logs.
- AC-5: Semantic extraction remains disabled unless and until a separate explicit decision approves a specific extraction policy and evidence contract.

## Risks

- Native API shapes evolve; pin fixture/API versions and retain source IDs and adapter versions.
- Chat and issue payloads can contain private or sensitive content; minimize fixture content and enforce access/retention controls before any real-source rollout.
- A graph can imply causality that the source never asserted; persist only explicit relationships in the first slice and mark extraction origins clearly.
- Provider rate limits, deletions, edits, and permission changes can make an incremental replica stale; keep cursors, observation times, replay behavior, and per-source failures visible.
- A disposable Neo4j test database may require Docker or an available Neo4j service; choose the test/runtime setup before implementation tasks are approved.

## Proposed Python package layout

```text
ingestion/
├── pyproject.toml
├── README.md
├── src/engineering_memory_ingestion/
│   ├── __init__.py
│   ├── config.py
│   ├── contracts/
│   │   ├── records.py          # Canonical Artifact, Actor, Provenance, SourceRef
│   │   ├── extraction.py       # Typed extracted values and evidence locators
│   │   └── versions.py         # Contract/schema versions
│   ├── core/
│   │   ├── runner.py           # Bounded source-to-store orchestration
│   │   ├── batch.py            # One normalized ingestion batch
│   │   ├── cursors.py          # Per-source incremental progress
│   │   └── errors.py           # Retryable/permanent/quarantined failures
│   ├── sources/
│   │   ├── base.py             # SourceAdapter protocol; raw payloads in, pages out
│   │   ├── github/{client,adapter,mapper}.py
│   │   ├── jira/{client,adapter,mapper}.py
│   │   └── slack/{client,adapter,mapper}.py
│   ├── extraction/
│   │   ├── deterministic.py    # IDs, URLs, timestamps, paths, explicit refs
│   │   └── semantic.py         # Disabled-by-default seam; no provider chosen yet
│   ├── storage/neo4j/
│   │   ├── driver.py           # Connection lifecycle/config
│   │   ├── schema.py           # Uniqueness constraints and indexes
│   │   ├── writer.py            # Idempotent record/edge upserts
│   │   └── queries.py           # Small, parameterized Cypher statements
│   └── observability/runs.py   # Counts, cursors, versions, redacted errors
├── tests/
│   ├── fixtures/sources/{github,jira,slack}/  # Native-shaped JSON API pages
│   ├── mocks/                    # Fixture-backed source adapters
│   ├── unit/                     # Mapping, validation, cursor, idempotency
│   └── integration/              # Disposable Neo4j graph write/read checks
└── docker-compose.yml            # Optional local Neo4j test service
```

Naming: lowercase `snake_case.py` modules and functions; `PascalCase` types; `UPPER_SNAKE_CASE` constants; provider-native IDs remain unchanged in `source_id`, while stable graph identity is namespaced (`provider:workspace:record_type:native_id`). Source mappers alone know provider field names. Core contracts and Neo4j writer consume canonical records only. Cypher uses fixed, parameterized queries and stable generic labels (`:Artifact`, `:Actor`); artifact kind and provider are properties, not interpolated labels. Source references become static, typed relationships only when an explicit source link exists.

The fixture directories are the first-slice mock source datasets: each stores representative native response envelopes (GitHub API objects, Jira issue/search shapes, Slack Web API message/thread shapes), including pagination metadata and linked examples. A fixture-backed adapter replays those responses without network or credentials. A local mock HTTP server is deferred unless provider clients need transport-level tests. Neo4j integration tests use a disposable Neo4j service; unit tests use a small fake writer/driver boundary and require no running database.
## Provisional implementation staging

1. Confirm scope and decisions; approve this specification before implementation.
2. Add the Python package layout and canonical record models/validation, with source-independent identifiers and provenance for Git history, hosted pull requests, Jira artifacts, and Slack threads.
3. Add source-faithful fixture datasets and replayable mock adapters; verify deterministic normalization.
4. Add adapters for Git history and hosted pull requests (both required), followed by the confirmed issue/chat providers; implement bounded backfill and incremental cursors while keeping provider details at the edge.
5. Add Neo4j constraints/indexes and an idempotent graph writer; test round-trip graph shape against a disposable database.
6. Add one end-to-end ingestion run path, structured run summaries, and failure/replay checks. Do not implement reasoning or semantic extraction in this slice unless separately approved.

## Open questions

- Confirm provider access details and required scopes for GitHub, Jira, and Slack before connector implementation.
- Confirm semantic extraction policy: default proposal is deterministic extraction only, with a disabled semantic-extractor seam.
- Confirm raw-payload retention: default proposal is to retain source-native payloads or durable references with provenance and access/retention controls.
- Confirm mock/test topology: proposed minimal route is native-shape JSON fixture datasets plus a local Neo4j test database; decide whether database containers or an existing Neo4j instance are available.
- Confirm the Git history acquisition route (local clone versus GitHub commit API); hosted pull-request metadata is required either way, with GitHub the current provider assumption.



