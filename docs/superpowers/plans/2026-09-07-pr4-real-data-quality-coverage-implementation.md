# PR4 — Real-Data Quality & Coverage — Implementation Plan

**Date:** 2026-09-07
**Branch:** `codex/pr4-real-data-quality`
**Base:** `a9081e61ffed598ba291211fa1e3a0e3efe2811e`

## Guardrails

- Preserve raw diagnostics, top-level `complete`, all demand/need/stockout/economics/allocation math, and fail-closed `None` values.
- Build user-facing causality exclusively from diagnostic codes and structured facts; never inspect English message text.
- Keep exact normalization/manual cluster mapping and canonical tariff money lookup unchanged.
- Keep data-quality entities PII-free and frontend rendering bounded to 100 rows per page.
- Limit the UI change to the existing Data screen; Flow remains PR5 scope.

## Task 1 — Contracts and pure grouping core

1. Add failing decision tests for immutable contracts, 100-route grouping, duplicate occurrence counts, distinct roots, worksheet repairs, unknown-code fallback, deterministic 5,000-diagnostic behavior, causal collapse, and orphan consequences.
2. Add `DataQualityLevel`, `DataQualityAffectedEntity`, `DataQualityIssueGroup`, and `DataQualityPresentation` to the decision contracts.
3. Add immutable internal `DataQualityFact` and pure deterministic `build_data_quality_presentation` in `backend/decision/data_quality.py`.
4. Implement explicit Russian copy/rules, unique entity counting, raw occurrence counting, deterministic entity/group order, and proven-identity consequence attachment.

## Task 2 — Tariff coverage classification

1. Add failing fixtures for route-pair absent, volume gap, price gap, required price, and ambiguous match, with parity assertions against canonical `expected_logistics` output.
2. Add a read-only tariff-gap classifier that shares canonical eligibility predicates where practical and never chooses a money result or fallback.
3. Assemble route facts from normalized products, tariffs, and canonical logistics diagnostics; include volume/price context and exact route identity.
4. Add regression coverage proving unresolved source clusters stop at cluster resolution and do not become missing-tariff facts.

## Task 3 — Stock, product, and Unitka evidence

1. Add failing tests distinguishing absent availability, unknown FBS, conflicting FBS, and known zero.
2. Add structured SKU facts for seller-stock, product-economics, and product-volume roots without changing planning values.
3. Preserve article/source-row evidence at the Unitka join boundary for out-of-universe, conflicting, and ambiguous article mappings.
4. Verify out-of-universe articles remain warnings, conflicts remain separate, and active-SKU demand/need remain available when downstream economics or stock is blocked.

## Task 4 — Snapshot and API integration

1. Add failing snapshot/API acceptance assertions for `snapshot.data_quality`, unchanged raw diagnostics/input statuses/top-level completeness, no PII, and business-output invariance.
2. Build structured facts where imports, normalized products, tariffs, availability, and identities coexist in `run_analysis_pipeline`.
3. Pass the completed presentation into the snapshot assembler; keep `snapshot.py` an immutable assembler.
4. Export the contracts and builder through `backend.decision` and rely on the existing dataclass wire serializer.

## Task 5 — Bounded Data-screen presentation

1. Add failing frontend tests in the repository's static/Node style for Russian hierarchy, collapsed details, accessible search, one card for 384 entities, and 100-row entity/raw pages.
2. Add pure client-side search/page helpers only for presentation; consume backend group level/count/copy/blocks without causal inference.
3. Render quality sections/cards and exact affected-entity drill-down with native `<details>`, `<button>`, labelled search, paging, and explicit text severity.
4. Move raw diagnostics into a collapsed, searchable, 100-row technical disclosure while retaining the cluster mapping and input-status UI.
5. Add scoped CSS using existing tokens and visible focus/forced-colors behavior.

## Task 6 — Verification and review

1. Run all required focused pytest commands, full pytest, compileall, four Node syntax checks, `git diff --check`, and repository status checks.
2. Review `main...HEAD` against every PR4 guardrail: unknown stays unknown, no message parsing, causal proof only, article evidence, no PII, bounded DOM, no PR5/business-math drift.
3. Commit once the final tree is green, create one PR to `main` with the required coverage-investigation report, and push the final HEAD.
4. Wait for fresh GitHub CI on final HEAD; report every required check and do not call the PR merge-ready unless Python, full pytest, Node, and Windows portable smoke all succeed.
