# Superpowers Archive

This directory contains **completed, abandoned, or superseded historical design and implementation documents**.

## Agent/Codex rule

`docs/superpowers/archive/**` is **not an active implementation source**.

Agents must not read, search, quote, infer current requirements from, or implement from this directory during normal development. Open archived files only when the user explicitly asks for one of:

- historical rationale;
- comparison with an older design;
- audit of superseded work;
- reconstruction of project history.

An archived document has no precedence even if its own old text says `approved`, `canonical`, `source of truth`, or contains executable-looking implementation steps.

## Active documents

Current active product/API designs live in:

```text
docs/superpowers/specs/
```

Current active implementation plans live in:

```text
docs/superpowers/plans/
```

`AGENTS.md` defines the required active reading order.

## Archive layout

```text
archive/specs/   superseded design/spec documents
archive/plans/   completed or superseded implementation plans
```

Git history remains the final provenance if a moved historical document needs to be compared with the exact commit in which it was originally active.
