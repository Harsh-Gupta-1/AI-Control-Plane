# Architecture

## Purpose

The AI Computer Control Plane enables an LLM to propose structured actions against an isolated computer environment while Python software governs what may happen, performs execution, records the resulting state, and verifies completion. The LLM supplies reasoning; it is not an execution authority or the source of truth.

## System boundaries

```text
User goal
    |
    v
Brain: LLM provider / agent reasoning
    |  proposes typed plan steps and tool requests
    v
Control Plane: runtime, state, registry, policy, approval, verification, trace
    |  executes only authorized registered tool requests
    v
Computer: Docker sandbox and its workspace/browser/processes
    |  returns structured observations
    +------------------------------------------------------------^
```

The host machine is outside the system's execution authority. Only the sandbox adapter may communicate with Docker, and its configuration must bind no host directories or host credentials into the agent-visible environment. The sandbox exposes its dedicated `/workspace`, `/downloads`, `/input`, `/output`, and `/temp` paths—not Windows paths.

## Proposed repository structure

```text
.
├── AGENTS.md
├── docs/
│   ├── architecture.md
│   └── mvp.md
├── pyproject.toml                    # added when executable Python code begins
├── src/control_plane/
│   ├── domain/                       # typed task, plan, action, observation, result models
│   ├── runtime/                      # task lifecycle and state transitions
│   ├── tools/                        # registry, tool contracts, individual tool adapters
│   ├── policy/                       # deterministic authorization rules and decisions
│   ├── approval/                     # approval request and resolution boundary
│   ├── sandbox/                      # Docker lifecycle and sandbox command boundary
│   ├── llm/                          # replaceable provider and agent-facing contracts
│   ├── verification/                 # outcome checks and completion evidence
│   ├── tracing/                      # append-only execution trace contracts/sinks
│   └── evaluation/                   # controlled task-suite definitions and runners
└── tests/
    ├── unit/
    ├── integration/
    └── evaluation/
```

This is a target layout, not an instruction to create empty modules during M0. A minimal `pyproject.toml` and package directory become appropriate once M1 introduces runnable, tested Python code.

## Major components and responsibilities

| Component | Responsibility | Must not own |
| --- | --- | --- |
| `domain` | Stable typed value objects and schemas: task state, plans, tool requests, observations, results, policy decisions. | I/O, Docker, provider SDK objects. |
| `runtime` | Drives legal task-state transitions; coordinates planning, authorization, execution, observation, replanning, and completion. | Security decisions, direct computer I/O, provider-specific logic. |
| `llm` | Defines a replaceable interface that converts task context and available tool schemas into a proposed next action or plan. | Execution, state mutation, authorization. |
| `tools` | Defines tool contracts and a registry; translates registered requests to sandbox operations and structured results. | Policy decisions, task lifecycle ownership. |
| `policy` | Applies deterministic rules to a normalized tool request and returns `ALLOW`, `APPROVE`, or `BLOCK`. | LLM judgment and tool execution. |
| `approval` | Pauses an approved task awaiting a human decision and records that decision. | Reinterpreting policy or executing tools directly. |
| `sandbox` | Creates, inspects, and disposes of Docker-isolated execution environments; returns bounded observations. | Agent planning and host access on behalf of a task. |
| `verification` | Evaluates explicit completion criteria using evidence from observations and tool results. | Declaring success from model narration alone. |
| `tracing` | Records structured lifecycle events and causal identifiers. | Controlling runtime behavior. |
| `evaluation` | Defines repeatable controlled tasks and measures execution reliability/safety. | Production execution authority. |

## Core interfaces

Interfaces should be Python `Protocol`s or small abstract base classes with domain-only inputs and outputs. Exact names can evolve, but their ownership must remain stable.

| Boundary | Request | Response | Rule |
| --- | --- | --- | --- |
| Runtime → LLM | immutable task context, plan/state summary, tool schemas | proposed plan or `ToolRequest` | Proposal only; malformed output is rejected by the runtime. |
| Runtime → Policy | normalized `ToolRequest`, task/sandbox context | `PolicyDecision` (`ALLOW`, `APPROVE`, `BLOCK`) and reason | Deterministic and side-effect free. |
| Runtime → Approval | approval request containing the policy decision and action summary | approve/reject/expire | Runtime does not execute while pending. |
| Runtime → Tool registry | policy-authorized `ToolRequest` plus execution context | `ToolResult` with observation or structured failure | Registry resolves only registered tools. |
| Tool → Sandbox | constrained sandbox operation | structured sandbox response | Tool adapters never receive host paths or unrestricted host handles. |
| Runtime → Verification | completion criteria and accumulated execution evidence | verified / not verified / inconclusive | Completion is evidence-based. |
| Runtime → Trace | lifecycle event | acknowledgement | Trace emission must not alter authorization. |

`ToolRequest` should carry a tool name, schema-validated arguments, task ID, action ID, and a declared capability. `ToolResult` should carry status, bounded output/observation, relevant artifacts, and a machine-readable error category. The runtime assigns IDs and controls transitions; an LLM cannot manufacture authority by placing IDs in text.

## Dependency direction

Dependencies point inward toward `domain`; runtime coordinates outward-facing interfaces without taking implementation dependencies on a particular LLM or sandbox technology.

```text
domain  <- runtime <- application/composition root
domain  <- policy
domain  <- approval
domain  <- verification
domain  <- tracing
domain  <- llm adapters
domain  <- tools <- sandbox adapters

application/composition root -> concrete adapters -> runtime interfaces
```

The composition root is the only place that wires concrete implementations together. In particular, tool implementations depend on a narrow sandbox interface, never on the runtime internals; policy depends on request data, never on tool implementation objects; and LLM adapters depend on external SDKs only inside `llm`.

## State ownership and execution flow

The runtime owns the canonical in-memory task state for the MVP: goal, plan, current step, action history, observations, pending approval, and completion status. The sandbox owns ephemeral computer state. The LLM sees a bounded representation of runtime state and proposes the next step; it does not mutate state.

For each requested action, the runtime validates the schema and task state, normalizes the request, obtains a policy decision, obtains human approval when required, calls the registered tool through the controlled dispatcher, records the result, updates state, and invokes verification or replanning as appropriate. All transitions and decisions later become trace events. Persistence/checkpoints are deferred, but the state model and event identifiers should permit them without changing the core interfaces.

## Security and bypass prevention

The enforcement point is a single runtime-controlled dispatcher. Only it may call a tool's internal execution method; tool implementations are constructed privately by the composition root and receive a restricted sandbox capability rather than arbitrary filesystem, subprocess, or Docker access. Public callers receive tool schemas and return results, not callable execution handles.

Policy evaluates the normalized request before dispatch. A blocked request cannot reach a tool. An approval-required request becomes a pending state and cannot reach a tool until a recorded human decision permits it. The registry rejects unknown tool names and validates arguments against the registered schema. Defense in depth comes from the Docker sandbox, whose process and filesystem namespace are separate from Windows; control-plane code must not offer a host-backed alternate path.

These architectural constraints require tests that prove, at minimum, unknown tools, malformed requests, blocked actions, and unapproved actions cannot produce tool execution.

## Extension points

- New LLM providers implement the narrow LLM interface and map provider output into domain proposals.
- New tools implement the tool contract, register a schema/capability, and use only sandbox services.
- Richer policy rules and approval UIs remain behind their respective interfaces.
- Docker may later be replaced by another compatible sandbox adapter only if it preserves the same isolation guarantees.
- Checkpoint stores, trace sinks, recovery strategies, and evaluators can be added as optional adapters after the MVP state model is established.

## Major architectural decisions

1. Use a modular monolith: one Python process and explicit interfaces, not microservices or queues. The MVP has no demonstrated need for distributed coordination.
2. Treat tools as typed capabilities, not arbitrary shell strings or model-authored code. Terminal capability may accept constrained command requests only after its own design and policy rules are defined.
3. Make policy deterministic, synchronous, and side-effect free. LLM reasoning can suggest an action but cannot decide whether it is allowed.
4. Place isolation in Docker rather than attempting OS or container-runtime implementation. Docker configuration is part of the security boundary and must be integration-tested.
5. Prefer structured observations/results over free-form logs so state updates, recovery, verification, traces, and evaluation have reliable inputs.
6. Begin with in-memory task state and local trace output. Add persistence only when checkpoint/resumption requirements are implemented and justified.

## Major risks and mitigations

| Risk | Mitigation |
| --- | --- |
| Prompt injection or unreliable model output drives unsafe actions. | Schema validation, capability-limited tools, deterministic policy, human approval, and sandboxing. |
| A future convenience path bypasses authorization. | One dispatcher, private tool execution methods, restricted adapter dependencies, and negative authorization tests. |
| Docker is misconfigured and exposes the Windows host. | No host mounts/credentials by default, explicit sandbox configuration review, and integration tests that inspect isolation assumptions. |
| State diverges from the actual sandbox after failures/timeouts. | Structured observations, bounded command results, verification, and later checkpoints/recovery. |
| Unbounded output or long-running processes exhaust resources/context. | Output/time/resource limits at sandbox and tool boundaries; process handling designed before terminal implementation. |
| Provider-specific behavior leaks throughout the codebase. | Domain contracts and provider adapters at the edge; contract tests using a fake provider. |
| Premature abstraction or infrastructure slows delivery. | Modular monolith, small interfaces, no database/event bus until a concrete need exists. |

## Explicit non-goals

MVP design does not include an operating system, custom container runtime, distributed system, database-backed platform, Kafka/message queues, RAG, document management, repository intelligence, coding-assistant features, computer vision, LLM training/fine-tuning, or a shallow browser-automation demo. Browser automation is a later sandboxed tool capability, not the project itself.
