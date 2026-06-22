# Project-Root Mode

Project-root mode means Agent Context Engine is installed directly into the repository
where you actively work.

## When To Use It

Use this mode when:

- you mostly work in one repository
- you want the simplest mental model
- you want the runtime state to live with that project
- you want Codex or Claude to feel natural from the current root

## User Experience

In the common case:

1. install Agent Context Engine into the project root
2. start the supported client from that root
3. project-local hooks and runtime state apply directly

This mode minimizes the need to think about external workspace activation or a
central shared runtime.

## Good Fit

- local-first individual workflows
- one project at a time
- users who do not want wrappers as their primary mental model

## Tradeoff

If you later want one shared memory runtime across many repositories, a central
installation may become a better fit.
