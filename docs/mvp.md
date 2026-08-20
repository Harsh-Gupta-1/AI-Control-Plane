# MVP Plan

## MVP goal

Demonstrate a local, Docker-isolated AI computer control plane that accepts a task goal, lets a replaceable LLM propose structured actions, governs every action through deterministic policy and optional human approval, executes only registered sandboxed tools, observes results, verifies completion, and produces an inspectable execution trace.

The MVP proves governed execution reliability on a small, controlled task suite. It does not aim to be a general autonomous operating environment.

## Scope

The MVP will include a single-process Python control plane; typed task and action state; a registered tool framework; Docker isolation; sandboxed filesystem and terminal tools; a bounded browser capability; a replaceable LLM abstraction with one local-provider adapter when justified; an action/observation loop with replanning; deterministic policy decisions; human approval pauses; evidence-based verification; and structured traces/evaluations.

## Explicit non-goals

- Building an OS, container runtime, distributed system, or multi-agent platform.
- Host filesystem access by the agent or its tools.
- Training/fine-tuning models, RAG, document systems, repository intelligence, or coding-assistant functionality.
- Production-scale persistence, scheduling, tenancy, or deployment infrastructure.
- Treating a successful model response as completion without independently collected evidence.

## Milestone order and completion criteria

| # | Milestone | Depends on | Complete when |
| --- | --- | --- | --- |
| M0 | Documentation foundation | — | Architecture, scope, risks, rules, and milestone plan are reviewed; no application functionality exists. |
| M1 | Foundation, runtime, and state | M0 | Typed domain models and a deterministic task lifecycle exist with unit tests for legal/illegal transitions; no LLM or computer execution is required. |
| M2 | Tool framework | M1 | Registered tool schemas, validation, a deny-by-default policy gate at the dispatcher boundary, fake tools, and tests proving unknown/malformed or unauthorized calls are rejected exist. |
| M3 | Docker sandbox | M2 | A disposable Docker sandbox contract/lifecycle is available and integration-tested for workspace layout and isolation assumptions; it exposes no host workspace. |
| M4 | Filesystem and terminal tools | M2, M3 | Sandboxed filesystem and terminal tools return structured bounded results, including failures and process output; integration tests run inside Docker. |
| M5 | Browser capability | M2, M3 | A minimal sandboxed browser adapter supports navigation, interaction, extraction, and downloads with controlled test pages and resource limits. |
| M6 | LLM abstraction | M1, M2 | Provider-neutral proposal interface, fake provider, and one local adapter (for example Ollama) exist with contract tests; provider objects do not leak into runtime state. |
| M7 | Agent execution loop | M1, M2, M4, M6 | The runtime can plan/propose, authorize, execute, observe, update state, and replan in controlled scenarios. Browser participation is optional here and added after M5. |
| M8 | Policy and approval | M2, M7 | The initial dispatcher gate expands into the complete deterministic `ALLOW`, `APPROVE`, or `BLOCK` rule set; approval pauses/resumes correctly; negative tests prove blocked/unapproved actions never execute. |
| M9 | Verification, recovery, and checkpointing | M1, M4, M7, M8 | Completion criteria are evaluated from evidence; basic failure classification/replan paths work; checkpoint/resumption is introduced only with a justified local persistence design. |
| M10 | Tracing and evaluation | M1, M7, M8, M9 | End-to-end traces cover lifecycle events, and a controlled task suite measures simple, multi-tool, recovery, safety, and interrupted/resumed cases. |

The ordering intentionally establishes the dispatcher and Docker boundary before capability tools, then introduces the LLM adapter before the autonomous loop. M2 includes a minimal deny-by-default policy gate so no tool can ever bypass authorization; M8 adds the complete policy taxonomy and human approval experience after the execution loop has a stable contract.

## Validation requirements

Each milestone requires unit tests for its local rules and contract boundaries. Milestones that cross the sandbox boundary require Docker integration tests. M7 onward requires controlled end-to-end scenarios using a fake LLM for determinism, plus limited runs against the selected local model to validate tool-call interoperability.

Security-focused tests must demonstrate that unknown tools, invalid arguments, host-path attempts, policy-blocked actions, and approval-pending actions cannot cause execution. Completion tests must use observable evidence, such as sandbox file state, command exit/result data, or browser extraction—not model text alone.

Manual validation should confirm Docker is available and the sandbox workspace is isolated; inspect representative traces; walk through approval pause/resume; and review Docker configuration for host mounts, credentials, network exposure, output limits, and cleanup behavior.

## Minimum reasonable dependencies

M0 requires no Python dependencies. At M1, use the Python standard library where possible: `dataclasses`, `typing`, `enum`, `pathlib`, `json`, and `unittest` are sufficient for initial models and tests. Add `pytest` only if its test ergonomics are chosen deliberately. Add Docker and a local LLM client library only at the respective integration milestones, preferably behind adapters; use direct HTTP through the standard library if that keeps the initial provider boundary simpler. Browser dependencies belong exclusively to M5 and must run in the sandbox.

Dependency additions must be justified by the active milestone, pinned appropriately, and kept out of domain models.

## MVP acceptance view

The MVP is complete when controlled tasks can be executed in a disposable sandbox through registered tools; every action has a recorded deterministic policy decision; risky actions can wait for explicit approval; the runtime handles observed failures through a defined replan/recovery path; completion is independently verified; and the resulting trace/evaluation makes success, failure, and blocked behavior auditable.
