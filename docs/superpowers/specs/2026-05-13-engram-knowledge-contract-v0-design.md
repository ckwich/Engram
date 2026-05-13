# Engram Knowledge Contract v0 Design

Status: Proposed product enhancement
Date: 2026-05-13
Scope: Public, generic, local-first, agent-facing Memory OS contract hardening

## Purpose

Engram Knowledge Contract v0, abbreviated EKC v0 in this document, gives agents
a typed way to ask Engram for task-shaped project context without rediscovering
the same orientation facts through repeated search calls.

The enhancement is inspired by Pinecone Nexus and KnowQL patterns, but it is
not a Pinecone integration, not a KnowQL clone, and not a new general-purpose
query language. It is an Engram-native MCP request and response contract over
local, reviewed, evidence-backed memory.

The first product slice is deliberately narrow:

```text
one MCP tool
one deterministic artifact
one eval
```

The tool is `query_knowledge`. The first artifact is `project_capsule`. The
first eval measures whether project-orientation tasks require fewer tool calls
than search-only retrieval while preserving citation quality.

## Product Thesis

Classic search gives agents relevant chunks. Long-running coding and research
agents often need something more specific: a current, cited, policy-aware
project orientation packet with explicit failure states.

EKC v0 moves repeated orientation work out of every agent run and into a
deterministic capsule response. The value is not smarter reasoning. The value
is a legible contract:

- the agent declares the project and task shape
- Engram chooses a project capsule path
- Engram returns a typed answer, citations, freshness state, policy state,
  budget accounting, and explicit errors
- unsupported inference is not quietly promoted into fact

## Non-Goals

- Do not build local KnowQL.
- Do not add Pinecone or Nexus as a dependency.
- Do not add an autonomous compiler agent.
- Do not require byte, page, line, table, AST, or field-level citations for v0.
- Do not make graph traversal a default dependency for project orientation.
- Do not expand to entity profiles, evidence bundles, graph-path bundles, or
  contradiction packets in the first slice.
- Do not introduce automatic durable memory writes.
- Do not weaken local-first defaults or send local evidence to remote providers.

## Current Engram Fit

The existing codebase already has the right seams:

- `server_daemon_client.py` is the stable thin MCP entrypoint for multi-session
  agents.
- `engramd` owns Memory OS state and routes stable memory operations.
- `core/memory_os/runtime.py` owns the SQLite ledger, content-addressed store,
  LanceDB retrieval, Kuzu graph, jobs, transactions, snapshots, and firewall.
- `core/memory_os/planner.py` already produces an inspectable strategy receipt,
  but it is a small heuristic planner rather than a full knowledge contract.
- `core/project_capsule.py` already builds a no-write project capsule draft
  from context refs and quality signals.
- `server.py` exposes `prepare_project_capsule`, but that helper is a draft
  workflow, not a typed serving contract.

EKC v0 should reuse and harden these seams. It should not create a parallel
"knowledge engine" inside Engram.

## User Experience

An agent calls:

```json
{
  "contract_version": "engram.knowledge.request.v0",
  "request_id": "req-local-001",
  "ask": {
    "goal": "Get current project context for continuing implementation work.",
    "task_type": "project_orientation",
    "project": "Engram",
    "focus": ["Memory OS", "MCP interface", "project capsule"]
  },
  "shape": {
    "response_type": "project_capsule_summary",
    "format": "json"
  },
  "policy": {
    "allow_unreviewed_sources": false,
    "inference_policy": {
      "allow_marked_inferences": false,
      "allow_unsupported_inferences": false,
      "on_required_inference": "return_partial"
    },
    "write_behavior": "read_only"
  },
  "grounding": {
    "required": true,
    "citation_level": "artifact",
    "on_missing_grounding": "return_partial"
  },
  "freshness": {
    "max_artifact_age": "P14D",
    "on_stale": "return_stale_warning"
  },
  "budget": {
    "depth": "standard",
    "max_artifacts": 1,
    "max_source_reads": 12,
    "max_tokens_out": 2500
  }
}
```

Engram returns:

```json
{
  "contract_version": "engram.knowledge.response.v0",
  "request_id": "req-local-001",
  "status": "ok",
  "answer": {
    "project": "Engram",
    "summary": "Engram is a local-first daemon-owned Memory OS for agents.",
    "current_goals": [],
    "active_decisions": [],
    "constraints": [],
    "open_questions": [],
    "important_entities": [],
    "recent_changes": []
  },
  "citations": [],
  "freshness": {
    "state": "fresh",
    "artifact_generated_at": "2026-05-13T00:00:00-07:00",
    "source_snapshot_id": "memory_os:latest"
  },
  "policy": {
    "unreviewed_sources_used": false,
    "unsupported_inferences_used": false
  },
  "budget_used": {
    "artifacts_read": 1,
    "source_reads": 0,
    "tokens_out_estimate": 0
  },
  "planner": {
    "strategy": "project_capsule",
    "methods_used": ["artifact"],
    "omissions": []
  },
  "errors": []
}
```

## Request Contract

EKC v0 accepts a JSON object with these top-level fields:

| Field | Required | Meaning |
|---|---:|---|
| `contract_version` | yes | Must be `engram.knowledge.request.v0`. |
| `request_id` | no | Caller-provided id echoed in the response. |
| `ask` | yes | Goal, task type, project, and optional focus terms. |
| `shape` | no | Response type and format. Defaults to project capsule JSON. |
| `scope` | no | Review state, source kinds, and time range filters. |
| `policy` | no | Reviewed-source and inference rules. |
| `grounding` | no | Citation requirement and citation level. |
| `freshness` | no | Max artifact age and stale behavior. |
| `budget` | no | Artifact, source-read, and output ceilings. |

Only one task type is accepted in v0:

```text
project_orientation
```

Only one response type is accepted in v0:

```text
project_capsule_summary
```

Unsupported task types should return `schema_failed` with a typed error rather
than falling back to broad search.

## Response Contract

EKC v0 returns a JSON object with these top-level fields:

| Field | Required | Meaning |
|---|---:|---|
| `contract_version` | yes | Must be `engram.knowledge.response.v0`. |
| `request_id` | yes | Echoed or generated request id. |
| `status` | yes | Typed result status. |
| `answer` | yes | Project capsule summary or `null` when unavailable. |
| `citations` | yes | Artifact-level or chunk-level citation records. |
| `freshness` | yes | Fresh, stale, or unknown artifact state. |
| `policy` | yes | Whether unreviewed sources or unsupported inference were used. |
| `budget_used` | yes | Artifact, source-read, and output estimate counts. |
| `planner` | yes | Strategy, methods, and omissions. |
| `errors` | yes | Typed error objects. |

Allowed statuses:

- `ok`
- `partial`
- `no_answer`
- `stale_artifact`
- `policy_denied`
- `budget_exceeded`
- `schema_failed`

## Project Capsule Artifact

The v0 artifact shape is:

```json
{
  "artifact_type": "project_capsule",
  "artifact_version": "v0",
  "project": "Engram",
  "generated_at": "2026-05-13T00:00:00-07:00",
  "source_snapshot_id": "memory_os:latest",
  "source_refs": [],
  "summary": "",
  "current_goals": [],
  "active_decisions": [],
  "constraints": [],
  "open_questions": [],
  "important_entities": [],
  "recent_changes": [],
  "staleness": {
    "state": "fresh",
    "invalidated_by": []
  }
}
```

The first compiler may be deterministic and conservative. It may assemble a
capsule from existing reviewed/canonical project memories and retrieved chunks,
then attach artifact-level or chunk-level citations. It should prefer returning
`partial` over inventing unsupported content.

## Citation Levels

EKC v0 supports:

- `artifact`: the answer cites the generated capsule and its source refs.
- `chunk`: answer claims cite Engram memory chunks.

EKC v0 does not require field-level or locator-level citations. Those remain
future upgrades after the daemon can reliably produce source locators.

## Inference Policy

Default policy:

```json
{
  "allow_marked_inferences": false,
  "allow_unsupported_inferences": false,
  "on_required_inference": "return_partial"
}
```

Grounded synthesis may be allowed in a later version, but unsupported inference
must never be silently promoted into memory fact or high-confidence context.

## Freshness Rules

A project capsule is fresh when:

- its source refs still resolve
- its generated timestamp is within `freshness.max_artifact_age`
- the compiler version matches the current EKC v0 compiler version
- no source ref is explicitly stale or rejected

If freshness cannot be proven, return `partial` or `stale_artifact` depending
on the caller's `freshness.on_stale` setting.

## Policy Rules

EKC v0 must default to read-only behavior:

```json
{
  "write_behavior": "read_only",
  "allow_unreviewed_sources": false
}
```

The response must state whether unreviewed sources or unsupported inferences
were used. The correct v0 answer should usually report:

```json
{
  "unreviewed_sources_used": false,
  "unsupported_inferences_used": false
}
```

## Failure Behavior

Schema and policy failures are product behavior, not exceptions leaking across
the MCP transport.

Examples:

- Unknown contract version: `schema_failed`
- Missing `ask.project`: `schema_failed`
- Unsupported task type: `schema_failed`
- `allow_unreviewed_sources=false` and no reviewed sources are available:
  `no_answer` or `partial`
- No source refs for the capsule: `partial`
- Max artifacts is less than 1: `budget_exceeded`

## Evaluation

The first eval compares:

```text
search-only project orientation
project-capsule EKC orientation
```

Questions:

- What is Engram's current architecture direction?
- What are the active constraints around reviewed writes?
- What should an agent know before modifying the MCP interface?
- What decisions already exist about local-first memory?
- What are the open questions for project capsule implementation?

Metrics:

- tool calls required
- approximate token output
- schema validity
- citation presence
- status correctness
- human-rated usefulness

Continuation threshold:

```text
EKC v0 is worth continuing if project-orientation tasks require at least 30%
fewer tool calls than search-only while preserving or improving human-rated
correctness and source traceability.
```

## Complete Enhancement Boundary

The complete EKC v0 product enhancement is done when:

1. Contract constants and normalization helpers exist.
2. A deterministic project capsule artifact path exists.
3. `MemoryOSRuntime.query_knowledge()` returns typed EKC responses.
4. The daemon exposes `/v1/query_knowledge`.
5. `EngramDaemonClient` exposes `query_knowledge`.
6. `server_daemon_client.py` exposes MCP tool `query_knowledge`.
7. `server.py` advertises the tool in `memory_protocol`.
8. Focused tests cover schema failures, policy defaults, successful capsules,
   stale/partial behavior, daemon routing, and thin-client routing.
9. A small eval compares EKC project orientation to search-only orientation.
10. Docs and release notes explain EKC v0, non-goals, and future phases.

## Future Work

After EKC v0 proves useful, the likely next slices are:

- chunk-level citations by default
- persistent capsule refresh jobs
- entity profile artifacts
- graph-path packets
- contradiction packets
- locator-level citations
- hosted/enterprise provider adapters
- optional Pinecone/Nexus adapter behind the Engram-native contract
