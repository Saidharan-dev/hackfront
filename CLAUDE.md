<!-- genesis:start -->
## Genesis workflow

Before changing this repository, load the Genesis and Ponytail skills and read `.genesis/KICKOFF.md`. Obey its phase instruction: do not write product implementation code during discovery, specification, or planning. Use the Genesis CLI for tasks, proof, decisions, approvals, and checkpoints. End every work session with `genesis checkpoint .`.

### Ask the index before reading the code

This repository is indexed. Querying it is faster than grepping and answers questions grep cannot.

- `genesis query . search NAME` — where a name is defined, when you know the name but not the file
- `genesis query . scope PATH` — what a file or directory depends on, and what depends on it
- `genesis query . callers REF` / `callees REF` — call edges for a symbol
- `genesis query . impact PATH` — everything that transitively imports a file. Run this before editing shared code; it is the blast radius
- `genesis query . path FROM TO` — how two files are connected
- Add `--json` for machine-readable output.

Start from the scope cards and symptom map already in `genesis brief .`; they point at declarations before you read anything. Treat every answer as advisory: it is static analysis, so confirm in source before relying on it. A result marked `ambiguous` means several definitions matched and none were ruled out — check the candidates rather than assuming the first.

Run `genesis serve .` when the structure is unclear or you want to show a human what changed. It draws the repository as a live map, reindexes on save, and is read-only. If the index looks stale and nothing is watching, run `genesis index .`.

Hosts that speak MCP can mount the same questions as tools with `genesis mcp .`.
<!-- genesis:end -->
