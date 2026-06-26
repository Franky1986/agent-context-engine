# Agent Context Engine Test Strategy And Validation Status

Last updated: 2026-06-26

This document defines a deterministic test order for Agent Context Engine and
tracks which parts have already been verified in recent installation,
integration, runner, and dreaming passes.

Platform note:

- macOS remains the supported active runtime target
- Windows is an experimental native runtime path and still requires one real
  Windows-machine validation pass before any support-level increase
- Linux and WSL remain scaffolded-only in the current validation model

## Relevant References

- [AGENTS.md](../../AGENTS.md)
- [AGENT_BOOTSTRAP.md](../../AGENT_BOOTSTRAP.md)
- [Runner And Harness Guide](../setup/RUNNER_HARNESSES.md)
- [Windows Installation Flow](../setup/WINDOWS_INSTALLATION.md)
- [Integration Management Runbook](integration-management.md)
- [README.md](../../README.md)

## Testing Strategy

Do not mix everything at once. Test in this order:

1. Installation and drift
2. CLI and retrieval
3. Integrations and wrappers
4. Hook capture per runner
5. Firewall and risk
6. Dreaming
7. Graph and semantic persistence
8. Monitor, LaunchAgent, and scheduler
9. Repair and reinstall
10. Multi-install and takeover/isolation

For every phase:

- define one expected state
- introduce one failure source at a time
- finish with a small documented pass/fail result

`./scripts/check --skip-runtime-db` intentionally runs the normal unit suite
without the heavy installation integration bucket. Run install, activation,
wrapper, LaunchAgent, and storage-root regression tests explicitly with:

```sh
./scripts/check --skip-runtime-db --include-install-integration-tests
```

The separated check reports `install-integration-suite` independently so a
slow install path cannot be mistaken for a generic unit-suite hang.

For the Windows experimental slice, keep two layers separate:

1. contract/generated-artifact validation on the current development host
2. one explicit real Windows install/activation/runtime pass

Current Windows setup validation has covered native `.cmd` command shims,
PowerShell hook/wrapper rendering, Task Scheduler script generation,
wrapper PATH resolution, gated monitor startup, late hook activation, and
frontend production build on a Windows host. Full runner-to-retrieval evidence
for a fresh external Windows project remains tracked by the matrix below.

### Windows Retrieval Validation Matrix

Use this matrix only on a real Windows machine or Windows VM. The goal is to
close the remaining gap between the current contract tests and true end-to-end
retrieval evidence.

Keep the scope narrow. Do not mix dreaming, monitor UI checks, and takeover
flows into the same pass.

`WIN-RET-01` CLI retrieval smoke

- Setup:
  - one active Windows installation
  - one test project root
  - no special graph or dream prerequisites
- Action:
  - `agent-context-engine doctor`
  - `agent-context-engine last --limit 5`
  - `agent-context-engine search "test" --limit 5`
  - `agent-context-engine retrieve "test" --limit 5`
- Expected:
  - all commands exit `0`
  - no path parsing failure
  - no PowerShell/cmd wrapper error
  - retrieval output includes `retrieval_run:`

`WIN-RET-02` startup context commands

- Setup:
  - same install as `WIN-RET-01`
- Action:
  - `agent-context-engine session-start-context`
  - `agent-context-engine repo-context --list`
  - `agent-context-engine personal-context --list`
- Expected:
  - all commands exit `0`
  - output remains readable with Windows paths
  - no malformed slash/backslash rendering breaks command hints

`WIN-RET-03` local project retrieval with explicit workdir

- Setup:
  - one Windows project directory with an obvious unique string in a tracked
    file or summary fixture
- Action:
  - from that project directory run a short agent session
  - then run `agent-context-engine retrieve "<unique string>" --limit 5`
- Expected:
  - the session becomes retrievable
  - returned workdir/project metadata points at the Windows project path
  - no path normalization drops the drive letter

`WIN-RET-04` risk-filtered retrieval

- Setup:
  - at least one private or risky retrieval candidate in local memory
- Action:
  - `agent-context-engine retrieve "<private query>" --limit 10`
  - `agent-context-engine retrieve "<private query>" --limit 10 --include-risky`
- Expected:
  - default retrieval hides risky/private hits
  - `--include-risky` surfaces them
  - both runs complete without CLI or quoting errors

`WIN-RET-05` retrieval run auditability

- Setup:
  - run `WIN-RET-01` and `WIN-RET-04` first
- Action:
  - `agent-context-engine retrieval-runs --limit 10`
  - `agent-context-engine retrieval-run <retrieval_run_id>`
- Expected:
  - recent runs appear
  - result rows keep provenance and score breakdown
  - access log rows render normally on Windows

`WIN-RET-06` query expansion with German input

- Setup:
  - at least one indexed item whose canonical wording is English
- Action:
  - `agent-context-engine retrieve "hexagonale architektur" --limit 5 --json`
- Expected:
  - command exits `0`
  - payload contains deterministic query expansion
  - expanded queries include `hexagonal architecture`
  - top result is relevant rather than empty/noisy

`WIN-RET-07` hook-to-retrieval continuity

- Setup:
  - one runner integration active on Windows, preferably `codex` first
- Action:
  - start one short session from a Windows project
  - end the session
  - run `agent-context-engine last --limit 5`
  - run `agent-context-engine retrieve "<phrase from the session>" --limit 5`
- Expected:
  - the session is visible in `last`
  - retrieval can find the fresh session content
  - no wrapper/hook path mismatch prevents indexing

`WIN-RET-08` monitor retrieval API parity

- Setup:
  - local monitor running on Windows
- Action:
  - open `/api/search?q=test&limit=5`
  - open `/api/retrieve?q=test&limit=5`
  - open `/api/retrieval-runs?limit=10`
- Expected:
  - endpoints answer
  - retrieval result shape matches CLI semantics
  - no Windows-only path serialization issue appears in JSON

Minimum evidence to record for each Windows retrieval case:

- exact command
- exit code
- first 10-20 output lines or the relevant JSON fragment
- whether the path shape looked correct
- whether the result was correct, empty-but-valid, or wrong

## Recommended Test Environment

Use three installation scenarios:

1. `test-main`
2. `test-takeover`
3. `test-isolated`

Use separate project targets and one dedicated runtime root:

- `<workspace>/agent-context-engine-test-main`
- `<workspace>/agent-context-engine-test-takeover`
- `<workspace>/agent-context-engine-test-isolated`
- `<workspace>/ace-runner-project-a`
- `<workspace>/ace-runner-project-b`
- `<home>/.agent-context-engine-test-memory`

## Phase A: Installation And Baseline

Goal:

- discovery is correct
- install is correct
- global links are correct
- monitor and LaunchAgent are correct

Tests:

1. `install-discovery` on a fresh checkout
2. `install` with a central `memory_root`
3. `doctor`
4. `check-installation`
5. `launchagent-status --verbose`
6. `integrations-status`

Pass criteria:

- no inconsistent root, memory, or port values
- no replaced installation still appears active
- `session-start-hook-entry.md` uses `agent-context-engine`
- on Windows, generated `.cmd` launchers point at the expected local CLI and
  hook companions

## Phase B: CLI And Retrieval Basics

Goal:

- core CLI works without runner complexity

Tests:

1. `agent-context-engine doctor`
2. `agent-context-engine last --limit 10`
3. `agent-context-engine search "test" --limit 5`
4. `agent-context-engine retrieve "test" --limit 5`
5. `agent-context-engine session-start-context`
6. `agent-context-engine repo-context --list`
7. `agent-context-engine personal-context --list`

Pass criteria:

- no path failures
- no stale installation references
- output is parseable and either sensibly empty or sensibly populated

## Phase C: Wrappers And Integrations

Goal:

- every runner starts through the intended path
- hook bridges point to the active installation

Runner matrix:

1. `codex-ace`
2. `claude-ace`
3. `agy-ace`
4. `gemini-ace`
5. `opencode-ace`
6. `cursor-enable --target ...` plus Cursor itself

Per-runner test:

1. start from `ace-runner-project-a`
2. run a short session
3. end the session
4. `agent-context-engine last --limit 10`
5. verify the session appears
6. verify the workdir is the project, not the install root
7. verify `handover` or `use` works

Minimal prompt pair:

- `Create a one-sentence summary of this project.`
- `What did we just discuss?`

Pass criteria:

- session appears
- resume and handover work
- workdir is correct
- no wrong root in session metadata

## Phase D: Hook Capture In Detail

Goal:

- hooks really fire
- events land in memory, DB, and monitor cleanly

Per runner verify:

1. start event
2. user message
3. assistant message
4. tool event
5. session end
6. token and usage metadata when the runner provides them

Pass criteria:

- monitor shows events
- `last` shows the session
- `handover` finds the session
- no runner-specific metadata gap breaks resume

## Phase E: Firewall And Risk

Goal:

- local reads are treated differently from actual tool execution and network activity
- taint behavior is correct
- user control-plane lines work

Test cases:

1. harmless local read
2. ACE CLI read such as `agent-context-engine last --limit 10`
3. intentionally block-worthy command
4. taint case followed by local read and then tool execution
5. user control-plane lines such as `reset taint`, `hooks-status`, `firewall disable session`, `firewall enable session`

Useful commands:

- `agent-context-engine risk list --limit 20`
- `agent-context-engine risk show <risk_event_id>`
- `agent-context-engine firewall list`
- `agent-context-engine firewall show <rule_id>`

Pass criteria:

- `CommandLine` payloads are classified correctly
- `AbsolutePath` reads are classified correctly
- ACE CLI reads do not get routed into false risk blocks

## Phase F: Dreaming

Goal:

- the dream pipeline runs cleanly per runner
- errors are auditable
- persistence is meaningful

Tests:

1. create several small sessions
2. `dream --pending`
3. run once with codex
4. run once with cursor
5. run once with antigravity when intended
6. inspect dream status afterwards

Pass criteria:

- successful runs create artifacts
- failed runs are explainable
- antigravity uses the current non-interactive path rather than stale flags

## Phase G: Graph And Semantic Quality

Goal:

- dreams create useful graph and semantic artifacts
- weak material does not over-persist

Tests:

1. session with clear facts
2. session with weak or fuzzy claims
3. run a dream
4. inspect graph and semantic status
5. verify what persisted and what did not

Pass criteria:

- clear facts are kept
- weak claims are not hardened into memory
- review and defer paths stay visible

## Phase H: Monitor, LaunchAgent, And Scheduler

Goal:

- runtime status is consistent
- there is no mixed state between monitor and LaunchAgent

Tests:

1. start or restart the monitor
2. `launchagent-status --verbose`
3. inspect `/api/status`
4. inspect scheduler status
5. repeat after runner and dream actions

Pass criteria:

- no stale runtime cards
- no replaced installation still appears active
- status separates hook, wrapper, and runtime state clearly

## Phase I: Repair And Reinstall

Goal:

- self-healing works
- reinstall is deterministic

Tests:

1. break selected symlinks intentionally
2. `check-installation`
3. `repair-installation --apply`
4. `check-installation` again
5. install from a newly cloned directory
6. verify discovery recognizes existing shared globals
7. verify the default proposal names the takeover clearly
8. verify install does not require manual force guessing

Pass criteria:

- repair finds real problems
- repair does not rewrite foreign roots blindly
- reinstall from a new clone is deterministic and understandable

## Phase J: Multi-Install, Takeover, And Isolation

Goal:

- takeover and isolation are clearly distinguishable

Scenarios:

1. install `test-main`
2. install `test-takeover`
3. verify shared globals move
4. verify the old installation is no longer active
5. install `test-isolated` with `--instance-name` or `--isolated`
6. verify no shared global takeover happens
7. verify isolated commands exist

Then from all three roots:

- `command -v agent-context-engine`
- `command -v agy-ace`
- `command -v opencode-ace`
- start a session
- verify which installation is actually active

Pass criteria:

- takeover and isolation are clearly distinct
- docs, discovery, and runtime behavior agree

## Test Protocol Template

For each test case keep these columns:

1. ID
2. Area
3. Setup
4. Action
5. Expected
6. Actual
7. Pass/Fail
8. Artifact
9. Follow-up issue

Example:

- `INT-AGY-01`
- `Integration / Antigravity`
- active installation `test-main`, start from `project-a`
- run `agy-ace`, send two prompts, end the session
- expect the session in `last`, correct workdir, working follow-up
- attach CLI output, session ID, risk ID, or screenshot

## Recommended Real Test-Day Order

1. Baseline install
2. CLI smoke
3. Codex
4. Claude
5. Antigravity
6. Gemini
7. OpenCode
8. Cursor
9. Firewall and risk
10. Dreaming
11. Graph and semantics
12. Repair
13. Takeover install
14. Isolated install

## 2026-06-26 Update Snapshot

- backend version `0.2.9`
- monitor version `0.6.7`
- cursor activation now persists configured background runner and launch workdir on hook
  generation
- session list and session detail now expose both origin client and background dream
  runner separately
- dream metadata hardening now records parse-failure signals (`AGENT_MEMORY_JSON_*`)
  for reconciliation and semantic parsing errors
- install/install-discovery and integration flows are now documented as multi-scenario:
  takeover, isolated, and cursor-specific activation with explicit `--background-runner`
- isolated install `agent-context-engine-refactor-2` validated target-local runtime
  storage, local SQLite, and LaunchAgent wiring
- retrieval smoke on `refactor-2` succeeded for both `search` and `retrieve`
- Cursor activation for a dedicated test project succeeded with
  `--background-runner claude`, and resulting Cursor sessions were summarized and dreamed
- a fresh automated public-checkout validation pass on the current macOS host
  completed direct CLI smoke for `doctor`, `check-installation`,
  `install-discovery`, `last`, `search`, `retrieve`,
  `session-start-context`, `repo-context --list`, `personal-context --list`,
  `integrations-status`, `launchagent-status --verbose`, and
  `dream-queue-status`
- the focused Windows experimental runtime contract slice is green on the
  development host (`10/10` focused tests)
- canonical repo knowledge now resolves from `memory/knowledge/repos.md` with
  legacy docs-path import fallback, and focused tests cover rebuild-index
  searchability plus install-discovery repo-index reporting
- follow-up hardening since that pass removed two concrete regressions:
  `agent-context-engine risk list --limit 5` now renders normalized category
  lists again, and the fresh-install smoke path now forces a non-interactive
  install invocation for automated checks

## Recommended Depth

Separate three levels:

1. smoke
2. contract
3. regression

Most important regressions:

1. `agent-context-engine` replaces stale path guidance in hooks
2. `agy-ace` sessions actually appear
3. `opencode-ace` sessions actually appear
4. shared-global takeover is deterministic
5. risk and firewall do not falsely block ACE reads

## Current Validation Status

Change set under test:

- backend version `0.2.9`
- monitor version `0.6.7`
- installation and integration command surface updated around `--installation-root`
- isolated install flow updated around deterministic local memory and wrapper behavior
- installation integration tests are now a separate `install-integration-suite`
  in `./scripts/check`
- dream JSON extraction and fallback hardening already included in this branch
- isolated install/runtime validation now includes `agent-context-engine-refactor-2`
  with local `memory/`
- runtime repo-index migration and canonical `memory/knowledge/repos.md`
  indexing/retrieval coverage are included in the focused regression slice

Status legend:

- `[x]` verified directly in recent runs
- `[~]` observed indirectly or only in prior install transcripts
- `[ ]` still open

### A. Installation And Baseline

- [x] `agent-context-engine doctor`, `agent-context-engine check-installation`, and `agent-context-engine install-discovery --target /private/tmp/ace-validation-target` completed on the current public checkout root.
- [x] the fresh `install-discovery` pass still exposes memory-root reuse, wrapper takeover, monitor-port defaults, and explicit user-confirmation requirements before mutation.
- [x] `install-discovery` exposes target, monitor port, memory root, and wrapper decisions before writing.
- [x] isolated installs in recent `test27`, `test28`, and `test29` runs revalidated the monitor port before writing config.
- [x] runtime bootstrap, monitor start, and LaunchAgent load completed in recent isolated install runs.
- [x] `session-start-hook-entry.md` now points at `agent-context-engine` instead of stale installation-only paths.
- [ ] the current public checkout install still reports LaunchAgent drift (`installed: no`, `loaded: no`) and no active local monitor runtime on the default port.
- [x] `python3 scripts/check_agent_context_engine.py --skip-tests --skip-runtime-db` now completes the fresh-install smoke path without the previous interactive install stall.
- [ ] fresh deterministic takeover-install regression after the latest install changes still needs one clean scripted pass.
- [ ] `repair-installation` still needs a targeted break-and-repair validation pass.

### B. CLI And Retrieval Basics

- [x] `doctor`, `last --limit 5`, `search "test" --limit 5`, `retrieve "test" --limit 5`, `session-start-context`, `repo-context --list`, and `personal-context --list` all completed successfully on the current public checkout install.
- [x] `last --limit 10`, `status --limit 10`, `dream-queue-status`, and `dream-v2-inspect` worked against `test29`.
- [x] `search "deutsche häuser" --limit 5` on `refactor-2` returned the expected fresh session/window artifacts.
- [x] `retrieve "Was wurde in den letzten Sessions über deutsche Häuser geschrieben?" --limit 5` on `refactor-2` succeeded and persisted a retrieval run.
- [ ] real Windows retrieval evidence is still missing for the dedicated matrix:
  `WIN-RET-01` through `WIN-RET-08`.

### C. Wrappers And Integrations

- [x] `agent-context-engine integrations-status` completed on the current public checkout install and reported `6/6 ready`; Cursor remains intentionally `hooks=not_prepared` on this root.
- [x] `cursor-enable --target ... --installation-root ...` wrote installation-root-aware bindings for `pr-llm-service`.
- [x] `cursor-enable --target <cursor-test-project> --installation-root <isolated-install-root> --background-runner claude` succeeded.
- [x] generated Cursor hook files now carry the effective launch workdir so routing resolves against the actual project path.
- [x] `cursor-status --target <service-test-project>` reported active hooks and one recorded session.
- [x] `cursor-status --target <cursor-test-project>` on `refactor-2` reported `9/9` active events, `background runner: claude`, and `background readiness: ready`.
- [x] `/api/integrations` for `test29` reported one activated Cursor project with `hooks_state=enabled` and `hooks_enabled=true`.
- [x] session list now shows `cursor` as origin client with separate dream runner metadata, and prefers `last_workdir` in session table paths.
- [x] session rows now render explicit origin/dream badges for quick provenance checks.
- [x] install-wide `doctor` / `check-installation` now mirror external Cursor project activations into `workspace_roots.cursor`, so the install-wide view matches `cursor-status --target ...`.
- [ ] full runner matrix for `codex-ace`, `claude-ace`, `agy-ace`, `gemini-ace`, and `opencode-ace` from dedicated project roots is still open.

### D. Hook Capture

- [x] recent `test29` state shows one codex session and one cursor session in `last`.
- [x] the Cursor project activation recorded `9/9` active hook events.
- [ ] explicit per-event validation for assistant messages, tool events, and session-end events across every runner is still open.
- [ ] direct revalidation that `agy-ace` and `opencode-ace` sessions appear reliably after the latest fixes is still open.

### E. Firewall And Risk

- [~] previous failure cases established the need to separate ACE reads from riskier tool execution.
- [x] a fresh automated CLI pass now confirms `agent-context-engine risk list --limit 5` completes and renders normalized category lists again.
- [ ] a fresh end-to-end firewall and taint matrix has not yet been rerun after the latest installation and integration fixes.
- [ ] explicit re-check that `agent-context-engine last --limit 10` no longer falls into false risk blocks is still open.

### F. Dreaming

- [x] `agent-context-engine dream-queue-status` completed on the current public checkout install and returned queue state without path or runtime-resolution failures.
- [x] `test29` has two successful pipeline-v2 dream runs in the queue.
- [x] codex dream run `dream_2026-06-24T11-14-19Z00-00_019ef955-756d-7330-bc4f-251778614e72_12943` succeeded with all 8 stages.
- [x] that codex run recorded usage in the LLM stages:
  - narrative: prompt `13759`, completion `808`, reasoning `516`
  - semantic extraction: prompt `13335`, completion `1258`, reasoning `794`
  - reconciliation: prompt `14934`, completion `2017`, reasoning `1531`
- [x] cursor dream run `dream_2026-06-24T11-22-03Z00-00_35578cb9-a3e0-4e0c-869d-90537c0000fc_31259` also succeeded with all 8 stages.
- [x] that cursor run recorded usage in the LLM stages:
  - narrative: prompt `52663`, completion `326`
  - semantic extraction: prompt `55153`, completion `511`
  - reconciliation: prompt `26210`, completion `468`
- [x] both successful runs wrote audit artifacts, including prompt manifests, `memory_changes`, `review_needed`, and `summary`.
- [x] isolated install `refactor-2` produced two Cursor sessions with `summary_status=summarized`, `dream_status=dreamed`, and `preferred_dream_runner=claude`.
- [x] stale shared-runtime dream state was recoverable through `scheduler-run --dream-enqueue-limit 0 --dream-queue-limit 0 --runner same-as-session --no-sync-neo4j`, leaving `running dreams: 0`.
- [x] queued follow-up hook events now revert covered session rows back to `dream_pending` immediately; any remaining non-zero `pending dreams` counts reflect real uncovered event ranges rather than stale row state.
- [ ] antigravity, gemini, and opencode dream paths still need revalidation after the JSON hardening work.

### G. Graph And Semantic Persistence

- [x] successful v2 dream runs reached semantic extraction, reconciliation, and persistence.
- [~] persisted semantic artifacts exist for the successful codex and cursor dream runs.
- [ ] the quality pass for entities, relations, and conservative persistence thresholds still needs a dedicated fact-vs-weak-claim review.
- [ ] assistant-message-specific semantic evidence should still be inspected explicitly in a fresh graph-quality pass.

### H. Monitor, LaunchAgent, And Scheduler

- [x] `agent-context-engine launchagent-status --verbose` completed on the current public checkout install and reported the expected LaunchAgent path and current loaded state.
- [x] recent isolated installs started a monitor and loaded a LaunchAgent.
- [x] `launchagent-status --verbose` for `refactor-2` showed the isolated local env file and `--runner same-as-session --graph-runner same-as-session` defaults for the normal install path.
- [x] `dream-queue-status` in `test29` reported `queued=0 running=0 failed=0 terminal_failed=0 succeeded=2`.
- [x] `dream-queue-status` in `refactor-2` reported `queued=0 running=0 failed=0 terminal_failed=0 succeeded=3` after the isolated validation runs.
- [x] `test29` monitor API confirmed the activated Cursor project and its hook state.
- [ ] `curl -sf http://127.0.0.1:8788/api/status` failed during this pass because no local monitor process was running for the public checkout root.
- [ ] a fresh `/api/status` drift audit after the latest monitor UI changes is still open.
- [ ] the Sessions UI change and the Cursor aggregate card should still be checked visually in a live monitor session.

### I. Repair And Reinstall

- [ ] no current branch pass has intentionally broken symlinks and then validated `repair-installation --apply`.
- [ ] no current branch pass has rerun a fresh reinstall smoke specifically to prove there is no more `--force` guesswork for normal takeover installs.

### J. Multi-Install, Takeover, And Isolation

- [x] isolated installs no longer rely on shared-global takeover as the intended path.
- [x] integration bindings now carry the active `installation_root`, which reduces cross-install drift for Cursor-style project activation.
- [x] one shared install (`refactor-1`) and one isolated install (`refactor-2`) were both exercised without reusing the same runtime root.
- [ ] one clean three-install matrix still needs to be executed on the latest code:
  - `test-main`
  - `test-takeover`
  - `test-isolated`
- [ ] `agent-context-engine`, `ace`, `agy-ace`, and `opencode-ace` should still be checked from all three roots after that matrix run.

## Observed Recent Runner Snapshot

From `refactor-2`:

- codex session `019efedc-d41a-7410-983b-89bfda283575`
  - summary: `summarized`
  - current dream status: `dream_pending`
  - one earlier queue entry succeeded
  - `pending dreams` remained non-zero because later event coverage still lagged `last_event_seq`

- cursor session `99979a47-1e71-4595-b0b0-e63543c1859e`
  - project: `<cursor-test-project>`
  - summary: `summarized`
  - dream status: `dreamed`
  - preferred dream runner: `claude`

- cursor session `746d43b2-371d-4d7b-9cd7-2f77c04669a1`
  - project: `<cursor-test-project>`
  - summary: `summarized`
  - dream status: `dreamed`
  - preferred dream runner: `claude`

From `test29`:

- codex session `019ef955-756d-7330-bc4f-251778614e72`
  - workdir: `<home>`
  - last dream run: succeeded
  - dream runner: `codex`
  - dream model: `gpt-5.4-mini`

- cursor session `35578cb9-a3e0-4e0c-869d-90537c0000fc`
  - transcript path was under the `pr-llm-service` Cursor project
  - `cursor-status` recorded one session for the activated project
  - `status --limit 10` still showed `dream=dream_pending`
  - dream queue entry for that session succeeded

This means the core Cursor activation path is working, install-wide activation
visibility now stays aligned with target-local Cursor status, and any remaining
`pending dreams` counts should be read as uncovered event ranges rather than
stale session-row state.
