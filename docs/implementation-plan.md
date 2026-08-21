# M4–M10 Implementation Blueprint — Master Index

This directory contains the complete, implementation-ready blueprint for completing the AI Computer Control Plane from M4 through M10.

## Reading Order for Gemini 3.1 Pro

Read these files **in exact order** before implementing anything:

1. `AGENTS.md` (project root)
2. `docs/architecture.md`
3. `docs/mvp.md`
4. `docs/plan-part01-audit.md` — Current architecture audit
5. `docs/plan-part02-target-architecture.md` — Global M4–M10 target architecture
6. `docs/plan-part03-m4-filesystem-terminal.md` — M4: Filesystem + Terminal Tools
7. `docs/plan-part04-m5-browser.md` — M5: Browser Capability
8. `docs/plan-part05-m6-llm.md` — M6: LLM Abstraction
9. `docs/plan-part06-m7-agent-loop.md` — M7: Agent Execution Loop
10. `docs/plan-part07-m8-policy-approval.md` — M8: Full Policy + Human Approval
11. `docs/plan-part08-m9-verification-recovery.md` — M9: Verification, Recovery, Checkpointing
12. `docs/plan-part09-m10-tracing-evaluation.md` — M10: Tracing + Evaluation
13. `docs/plan-part10-incremental-steps.md` — Incremental implementation steps (M4.1, M4.2, …)
14. `docs/plan-part11-interfaces.md` — Exact interface specifications
15. `docs/plan-part12-testing-security-deps.md` — Testing strategy, security architecture, dependencies
16. `docs/plan-part13-gemini-instructions.md` — Instructions for the implementation agent

## Critical Rules

- Implement one incremental step at a time (see `plan-part10-incremental-steps.md`).
- Run tests after every step.
- Never skip steps or implement future milestones early.
- Stop at every milestone boundary and ask the user to commit.
- Provide a single-line commit message at each milestone boundary.
- Follow the specified interfaces exactly.
- Never bypass the dispatcher. Never access the host filesystem.
