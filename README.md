# AI Computer Control Plane

![CI](https://github.com/<owner>/<repo>/actions/workflows/ci.yml/badge.svg)

This repository contains a local, Docker-isolated AI computer control plane. It accepts a task goal, lets a replaceable LLM propose structured actions, strictly governs every action through deterministic policy and human approval, executes only registered sandboxed tools, observes results, verifies completion, and produces an inspectable execution trace. It proves governed execution reliability on a small, controlled task suite.

## Architecture

The project maintains a strict boundary between three core components:

* **Brain (LLM)**: Proposes intent and actions. Replaceable, untrusted, and has no direct execution power.
* **Control Plane**: The source of truth for task state, validation, policy decisions, execution results, and completion. It acts as an absolute governor.
* **Computer (Sandbox)**: The isolated execution environment where authorized actions safely materialize.

```
+---------------+      +-------------------------+      +---------------------------+
|     Brain     | ---> |      Control Plane      | ---> |         Computer          |
| (LLM Adapter) |      | (Policy & Verification) |      | (Docker Sandbox / Tools)  |
+---------------+      +-------------------------+      +---------------------------+
```

## Key Properties

- **Deny-by-default policy gate**: Every tool invocation passes through a deterministic `ALLOW`, `APPROVE`, or `BLOCK` policy constraint. Unknown or unauthorized calls are dropped instantly.
- **No host access**: Computer interaction is permitted only inside the mandatory Docker sandbox. The agent never touches the host filesystem.
- **Cryptographically bound approval**: Human approval is cryptographically bound to the exact proposed tool arguments, ensuring the LLM cannot swap payloads after approval.
- **Evidence-based verification**: Task completion is verified using independently collected execution evidence from the sandbox, rather than relying on model text claims.
- **Full execution tracing**: Every plan, action, policy decision, approval, and verification is emitted as a structured, auditable trace.

## Project Structure

| Package | Responsibility |
| --- | --- |
| `src/control_plane/domain` | Core typed models (Task, ToolRequest, ToolResult, Constraints) |
| `src/control_plane/tools` | Registered tool schemas and framework (Filesystem, Terminal, Browser) |
| `src/control_plane/policy` | Deterministic authorization gates and capability checking |
| `src/control_plane/sandbox` | Docker container lifecycle, isolation, snapshotting, and execution |
| `src/control_plane/runtime` | Task state machine, tool dispatching, and agent event loop |
| `src/control_plane/verification` | Evidence-based completion rules |
| `src/control_plane/tracing` | Structured JSON lines emission of the execution lifecycle |
| `src/control_plane/approval` | Human-in-the-loop cryptographically signed authorization |
| `src/control_plane/llm` | Provider-neutral interfaces and LLM adapters (Fake, Ollama) |
| `src/control_plane/evaluation` | End-to-end task runner and metric collection |

## Quickstart

Clone the repository and install the package in editable mode:

```bash
git clone https://github.com/<owner>/<repo>.git
cd <repo>
pip install -e .
```

Run the live CLI demo in fake mode (no Docker or LLM required):

```bash
python -m control_plane.cli --goal "create notes.txt and verify it exists"
```

## Testing

The project uses `pytest` and clearly separates unit tests from sandbox integration tests.

- **Unit Tests**: Run with `pytest tests/unit -v`. Fast, offline, and require no external dependencies (Docker, LLM).
- **Integration Tests**: Run with `pytest tests/integration -v`. Requires the Docker daemon to be running.

## Status

This project implements the [MVP specifications](docs/mvp.md) and is functionally complete per the MVP milestones.
