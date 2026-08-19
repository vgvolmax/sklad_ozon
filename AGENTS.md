# Codex Cloud instructions

This repository is commonly developed with Codex Cloud.

## Source of truth

Before implementation, read:

1. `docs/superpowers/specs/2026-08-19-ozon-fbo-unit-economics-optimizer-design.md`
2. `docs/superpowers/plans/2026-08-19-mvp-implementation.md`

The design spec has precedence over the implementation plan. The implementation
plan has precedence over GitHub issue summaries. Do not redesign the agreed
architecture unless repository documents genuinely contradict each other or the
task explicitly requests an architecture change.

## Codex Cloud environment

Do not require authenticated GitHub CLI (`gh`) for normal implementation work.
Failure of `gh auth status` is not by itself a blocker. Do not require a tool
specifically named `make_pr`; use the native PR/publication capability available
in the Codex Cloud task. GitHub issue access is supplementary: if requirements
are already in the repository specification or plan, continue from those files.

## Network and dependencies

Do not require Agent Internet Access or direct npm registry probes as a
precondition for implementation. Use the standard Codex Cloud environment,
automatic setup, available package facilities and caches first. Do not run
`npm view` merely to test whether direct outbound network access is available.

When the current PR actually requires adding or installing dependencies,
perform the normal project operation required by the task. Treat dependency
availability as an environment blocker only if the actual required
installation, build or test workflow fails because the dependency cannot be
obtained. If that happens:

- report the exact failing command and error;
- do not redesign the agreed architecture;
- do not replace the agreed stack with ad-hoc vendored or hand-written
  substitutes merely to bypass the environment.

Agent Internet Access is not a general project requirement. Internet
availability in a particular Codex task is an execution-environment property,
not a product architecture decision.

## Work preservation

Do not delete valid, verified work merely because `gh` is unavailable. If native
PR publication is unavailable, preserve completed verified changes whenever the
environment permits and report the exact limitation. Follow stricter platform or
system instructions when they explicitly prevent preserving commits or branches.

## Development workflow

For implementation tasks:

- work outside `main`;
- follow the PR sequence in the implementation plan;
- do not start the next PR scope early;
- use TDD for behavior changes;
- run the verification commands defined by the current PR;
- do not claim success without fresh verification evidence.

## Scope discipline

Do not add features from later PRs. Implement only the current PR plus fixes
strictly required for its acceptance (YAGNI).
