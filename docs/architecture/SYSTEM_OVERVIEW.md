# System Overview

## Purpose

Agent Context Engine is a local-first runtime memory and context engine for coding
agents and their human operators.

It captures local session activity, stores operational state, supports
retrieval across prior work, compresses context through summary and dream
pipelines, enriches that memory through graph extraction, and exposes
inspectable safety and control surfaces.

## Public Product Shape

The public repository is intended to document and ship the full local product,
not just a narrow technical core.

Major public product areas:

- hooks and event capture
- wrappers and activation paths
- local persistence
- retrieval and query expansion
- summary and dreaming flows
- graph extraction and graph inspection
- monitor/API
- safety, approvals, and firewall controls

## High-Level Architecture

### Interfaces

- CLI entrypoint via `scripts/agent-context-engine`
- thin Python launcher via `scripts/agent_context_engine.py`
- hook ingestion through `backend/src/agent_context_engine/interfaces/hooks/`
- HTTP monitor server through `backend/src/agent_context_engine/interfaces/http/server.py`
- React monitor under `frontend/`

### Core Runtime

- application services under `backend/src/agent_context_engine/application/`
- domain logic under `backend/src/agent_context_engine/domain/`
- ports under `backend/src/agent_context_engine/ports/`
- infrastructure and adapters under `backend/src/agent_context_engine/infrastructure/`
  and `backend/src/agent_context_engine/adapters/`

### Contracts

- OpenAPI contract in `contracts/openapi.yaml`
- code-near `.spec.md` files for non-trivial boundaries

## Storage Model

Agent Context Engine is local-first.

Runtime data lives primarily under `memory/`:

- `memory/status/` for SQLite and operational state
- `memory/dream/` for dream artifacts
- `memory/graph/` for graph artifacts where applicable
- `memory/personal/` for personal memory
- `memory/knowledge/repos.md` for the local repository index

Optional external projection:

- Neo4j can be used as an optional graph projection layer

## Main Data Flows

### Hook -> Persistence -> Processing

1. client hooks emit session and tool-related events
2. events are normalized and written to local persistence
3. scheduler and follow-up flows build summaries, dream runs, and graph artifacts
4. results become inspectable through CLI and monitor views

### Retrieval

1. a user or agent asks through CLI or monitor
2. the query is normalized and optionally expanded
3. local retrieval runs against persisted memory and graph-conditioned context
4. results are filtered and logged

### Monitoring

1. the monitor reads local runtime state
2. it exposes views for sessions, dreams, graph, integrations, storage, and risk
3. bounded control actions are surfaced without turning the monitor into an
   unrestricted command surface

## Activation Model

Agent Context Engine does not have a single activation path.

The public product documents three explicit modes:

- project-root mode
- wrapper mode
- central-installation mode

See:

- [Activation Model](../setup/activation-model.md)
- [Project-Root Mode](../setup/root-mode.md)
- [Central Installation Mode](../setup/central-installation-mode.md)

## Safety Model

Agent Context Engine includes defense-in-depth safety controls:

- deterministic baselines where possible
- risk scanning
- approval and override handling
- firewall state and audit trails

These are local workflow controls, not a general sandbox replacement.

## Agent-First Operating Model

The public repository is meant to remain agent-first.

An agent should be able to:

- explain installation choices
- perform installation and activation setup
- retrieve and inspect prior work
- operate the monitor and CLI surfaces
- explain where data lives and how safety works

Explicit security and approval actions remain user-owned.
