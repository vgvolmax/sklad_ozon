# Codex Cloud instructions

## Source of truth

Before implementation, read the design specification and then the implementation
plan. The design has precedence over the plan, and the plan over issue summaries.

## Canonical runtime contract

```text
repository ZIP
→ extract
→ open app/index.html in browser
```

There is no launcher, server, runtime bootstrap or installation step. The active
MVP architecture has no `start.bat`, backend, localhost dependency, runtime Node
or package manager. Do not add TypeScript, a compiler, a bundler, or a build
pipeline without an explicitly approved architecture change.

Production HTML, CSS, JavaScript and required vendor assets are committed
directly. They must work through `file://`, use relative paths, and require no
runtime network access. Do not create empty future directories: apply YAGNI.

## Development and verification

- Use plain JavaScript and dependency-free `node:test` / `node:assert` tests.
- The canonical test command is `node --test`; do not add a package manifest only
  to run it.
- Agent Internet Access and an npm preflight are not required by the active
  architecture. Use an external resource only when a future task genuinely needs
  it.
- Work outside `main`, follow the PR sequence, use TDD for behavior changes, and
  run the current PR's fresh verification commands.
- Environment limitations must not cause architecture drift.

## Analytical safeguards and scope

The functional-core/imperative-shell boundary and every analytical correctness
invariant in the design specification remain mandatory. In particular, delivery
cluster is demand geography and origin/dispatch cluster is fulfillment origin.
Preserve report metadata, lifecycle and PII boundaries, incomplete-week handling,
stockout and distortion logic, clean routes, spreadsheet parity, economics,
feasibility, placement assessment, counterfactual logic, and optimizer limits.

Do not start a later PR early. Implement only the current scope and fixes required
for acceptance.
