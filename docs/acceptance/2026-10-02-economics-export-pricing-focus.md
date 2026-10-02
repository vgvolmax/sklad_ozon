# Economics: filtered export, prices, profit and focused articles

Approved scope: the five Economics follow-ups confirmed in the conversation on
2026-10-02. A separate PR from main `5340433`; no merge or auto-merge.

## Behavior

- Python owns product search/filter selection for the table, totals and XLSX.
  Every matching SKU exports, including beyond load-more. Shared/blank articles
  remain separate SKU rows. Existing numeric columns are preserved; SKU is appended.
  Empty selection disables export; failures allow retry; changed pending selection
  cannot offer a stale file.
- Minimum positive target price can be below current price. Lowering uses existing
  success green plus text/arrow/delta and a dedicated filter. Margin/ROI and
  unreachable/partial-route scenarios retain their existing calculation ownership.
- The compact summary uses the selected inclusive acceptance interval and selected
  products: current-rate delivered-route profit before advertising, known uploaded
  spend, and their difference once. Missing advertising is unknown; reported zero
  is zero. Partial profit and known expense coverage are explicit. This remains an
  Economics model, not a buyout/payout statement.
- Opening an article hides the other articles until collapse. Only its bounded
  cluster region scrolls on wheel over clusters; overscroll stays contained. A close
  strip stays outside horizontal table overflow. Collapse restores the list/window
  position and disclosure focus; edits preserve cluster scroll and selected SKU.
  The selected article's charts remain accessible; no global document lock.
- The small SKU copy icon is independent, accessible and has no hover tooltip.
  A tiny success popup appears after actual clipboard success; denial and
  superseded async clicks cannot announce false success.

## Verification

- Backend regressions were observed failing before implementation, then passing:
  selection/empty/error exports, duplicate/blank articles, formula-safe identities,
  minimum margin/ROI prices, unreachable goals, independent pre-ad profit, clipped
  advertising, reported zero, unknown DRR and incomplete routes.
- UI regressions were observed failing before the new summary/focus existed.
  Real loopback API and production Chromium now cover filtered XLSX contents,
  all matching rows beyond the display limit, retry, slow/stale searches/downloads,
  IME composition completion, resized-header collision, period summary, cluster containment/restoration, focused edits, charts,
  actual clipboard content, denial/races, keyboard and narrow/reduced-motion states.
- `PYTHONPATH=/tmp/econ-audit-deps python -m pytest -q`: **1936 passed**;
  one existing Starlette test-client deprecation warning.
- All eight CI JavaScript syntax commands pass; `git diff --check` passes.
- All four browser scenarios pass: Plan, Economics advertising, Economics periods,
  Economics focus. No JavaScript errors; synthetic fixtures and local API only.
  Desktop summary/focus and 390px focus screenshots inspected. CI retains screenshots.
- The premium strict static audit reports 31 literal-button warnings; the unchanged
  baseline reports 30. Its parser recognizes inline handlers only and cannot detect
  this application's programmatic listeners. The added copy/close/filter/download
  handlers are bound in `bind()` and exercised by real browser tests. These are
  reviewed parser false positives, not a claimed clean static-audit result.

The fresh whole-branch review found loss of load-more extent on focused global
scenario submission and an exact-cent target rounding defect. Both corrections
were reproduced by failing regressions before fixes; integer-kopek search preserves
exact margin/ROI/tax-breakpoint minima, and scenario submission retains the focused
list extent and collapse focus. Publication requires green Python/browser/Windows
portable CI for the exact published tree. Live Ozon accounts were not exercised.
