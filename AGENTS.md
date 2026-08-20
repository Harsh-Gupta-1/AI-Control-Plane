# AI Computer Control Plane — Project Rules

## Scope and principles

- This is a Python project for an AI computer control plane, not an operating system or a container runtime.
- The LLM is a replaceable reasoning component. Do not couple the architecture to a model, vendor, SDK, or serving system.
- The control plane, not the LLM, is the source of truth for task state, validation, policy decisions, execution results, and completion.
- All computer actions must be exposed as registered structured tools. An LLM or agent must never execute arbitrary computer actions directly.
- Every tool invocation must pass through deterministic policy enforcement before execution. Tools must not provide a public execution path that bypasses policy.
- Computer interaction is permitted only inside the mandatory Docker sandbox. The agent and tools must never access the Windows host filesystem.
- Preserve the separation of Brain (LLM), Control Plane (governance and orchestration), and Computer (sandbox). Do not cross these boundaries for convenience.

## Engineering constraints

- Keep interfaces simple, explicit, typed, and independently testable.
- Do not implement OS-level functionality, a custom sandbox/container runtime, distributed infrastructure, message queues, databases, RAG/document systems, repository intelligence, or LLM training/fine-tuning.
- Do not add dependencies without a concrete requirement and a short justification in the relevant design or implementation change.
- Do not add future-phase capabilities prematurely. Build only the active milestone.
- Every major feature requires automated tests plus appropriate manual validation.
- Update `docs/architecture.md` when a change affects boundaries, interfaces, state ownership, security assumptions, or dependency direction.
- Keep execution effects observable and structured; do not rely on free-form model text as evidence that an action succeeded.

## Development workflow

For each major component, document the problem, requirements, architecture, interfaces, and data/state design before implementation. Then implement, test, manually validate, review, and only then proceed to the next component.

When adding a tool, define its input/output schema, capability requirements, policy classification, sandbox behavior, failure behavior, and verification path. When adding an LLM provider, implement it behind the existing provider interface and do not let provider-specific objects escape into the control plane.

## Repository layout

The intended layout is documented in `docs/architecture.md`. M0 intentionally contains documentation only; do not create placeholder runtime code merely to populate the layout.
