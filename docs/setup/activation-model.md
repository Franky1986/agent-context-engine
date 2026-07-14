# Activation Model

Agent Context Engine can become active in multiple ways. Public documentation must make
this explicit because activation confusion is one of the main sources of setup
friction.

## Three Modes

### Project-root mode

Install Agent Context Engine directly into the project root you actively work in.

This is often the simplest path for:

- Codex
- Claude

In this mode, the local project root owns the hook setup and runtime state, so
starting the client from that root is usually enough.

### Wrapper mode

Start the client through an Agent Context Engine wrapper such as:

- `codex-ace`
- `claude-ace`
- `agy-ace`
- `gemini-ace`
- `opencode-ace`

This mode is useful when:

- you want one shared Agent Context Engine installation
- you work across multiple repositories
- the wrapper should resolve the active installation and then launch against
  the current project's local hook config

### Central-installation mode

Keep one central Agent Context Engine root and connect additional workspaces or
projects to it.

This is the more advanced shared-memory operating model and is best when one
runtime should support multiple repositories or clients.

## Equality Of Entry Paths

Project-root mode and wrapper mode are both valid public entry paths.

The docs should not imply that wrappers are always required. They are one
activation path, not the whole product model.

## Client Notes

- `codex`: project-root mode and wrapper mode are both relevant
- `claude`: project-root mode and wrapper mode are both relevant
- `cursor`: activation is primarily project/workspace-based
- `gemini`: wrapper/global-root behavior is important
- `opencode`: wrapper/central-root behavior is important
- `antigravity`: wrapper/global-root behavior is important

For client-specific details, see [Runner And Harness Guide](RUNNER_HARNESSES.md).
