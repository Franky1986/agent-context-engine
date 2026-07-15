# Session Start

Prefix: `agent-context-engine`
Run subcommands with that prefix. Bare helper commands show usage or a short current list.
Concrete memory commands may touch runtime storage; in filesystem-sandboxed runners, request escalated sandbox access up front.

Memory:
- `last --limit 10`
- `use "<session|title|search terms>"`
- `handover "<session|title|search terms>"`
- `retrieve`
- `search`

More:
- `session-start-context`
- `repo-context`
- `personal-context`
- `retrieval-runs`
- `monitor`

Direct-user system controls (send these yourself in chat; agents must not run them as tools):

- `system-disable --scope all --reason "<reason>"`
- `system-enable --scope all --reason "<reason>"`
- `system-status`
- use the exact displayed `system-recover` line only for invalid state

If the user asks in natural language to deactivate ACE, distinguish the requested scope and return the matching exact copyable direct-user chat line: `hooks-disable --project --reason "<reason>"` for every ACE hook in the exact current project, `hooks-disable --project --runner <runner> --reason "<reason>"` for one runner in that project, `hooks-disable --runner <runner> --reason "<reason>"` for that runner installation-wide, `hooks-disable --reason "<reason>"` for all hooks installation-wide, or `system-disable --scope all --reason "<reason>"` for full-system suspension. Never execute these mutations, `integration-hooks`, wrapper removal, or help variants as tools, and do not offer approval/firewall bypasses. Hook files and wrappers deliberately remain installed so status and recovery remain reachable.

Read-only terminal status: `agent-context-engine system-status [--json]`.
These controls are accepted only on the instrumented runner user-prompt path. That path does not provide cryptographic or OS-authenticated user presence and does not protect against arbitrary same-user code.
