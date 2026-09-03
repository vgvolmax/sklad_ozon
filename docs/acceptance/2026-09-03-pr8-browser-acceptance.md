# PR8 final browser acceptance — 2026-09-03

## Environment

| Item | Value |
| --- | --- |
| OS | Ubuntu container (Windows host is not available) |
| Browser | Not available in the execution environment |
| Browser version | N/A |
| Viewport | N/A |
| Zoom | N/A |

This report deliberately does not substitute source inspection, API tests, a
DOM shim, or a temporary development server for the required real-browser
walkthrough. The container has no Chrome, Chromium, Edge, Firefox, Selenium,
Playwright, or Pyppeteer installation. Network policy also prevents downloading
a browser. Because `start.bat` cannot be executed in this Linux container, the
canonical Windows launch path could not be exercised here.

## Browser acceptance evidence

Only `PASS` and `FAIL` are used as result values. Every browser scenario is
`FAIL` because it could not be executed in a real browser in this environment;
these results must not be interpreted as a defect in the application.

| Scenario | Result | Notes |
| --- | --- | --- |
| Plan — no objective selector | FAIL | Real-browser scenario not executed. |
| Plan navigation/state | FAIL | Real-browser scenario not executed. |
| Back/Forward | FAIL | Real-browser scenario not executed. |
| Flow destination | FAIL | Real-browser scenario not executed. |
| Flow origin | FAIL | Real-browser scenario not executed. |
| Flow SKU | FAIL | Real-browser scenario not executed. |
| Units metric | FAIL | Real-browser scenario not executed. |
| Share metric | FAIL | Real-browser scenario not executed. |
| Margin metric | FAIL | Real-browser scenario not executed. |
| Profit metric | FAIL | Real-browser scenario not executed. |
| Observed/Clean | FAIL | Real-browser scenario not executed. |
| Route drill-down | FAIL | Real-browser scenario not executed. |
| Incomplete route | FAIL | Real-browser scenario not executed. |
| SKU breakdown | FAIL | Real-browser scenario not executed. |
| Unit Economics | FAIL | Real-browser scenario not executed. |
| Route Economics | FAIL | Real-browser scenario not executed. |
| Recalculation lifecycle | FAIL | Real-browser scenario not executed. |
| 200% zoom | FAIL | Real-browser scenario not executed. |
| Narrow viewport | FAIL | Real-browser scenario not executed. |
| Keyboard-only | FAIL | Real-browser scenario not executed. |
| Focus return | FAIL | Real-browser scenario not executed. |
| Reduced motion | FAIL | Real-browser scenario not executed. |
| Forced colors | FAIL | Real-browser scenario not executed. |

## Automated verification evidence

The representative acceptance fixture remains the source of the two-SKU,
three-cluster dataset. It includes local and external fulfillment, observed and
clean evidence, complete and incomplete route economics, and a row whose Safe
Plan differs from Calculated Plan.

| Check | Result | Notes |
| --- | --- | --- |
| Full pytest | PASS | 467 passed. The environment needed the already-installed `httpx2` package exposed through `PYTHONPATH` because dependency downloads are blocked. |
| `core.js` syntax | PASS | `node --check` completed successfully. |
| `components.js` syntax | PASS | `node --check` completed successfully. |
| `flow.js` syntax | PASS | `node --check` completed successfully. |
| `app.js` syntax | PASS | `node --check` completed successfully. |
| Whitespace validation | PASS | `git diff --check` completed successfully before this report was committed. |
| Fresh GitHub Linux CI | FAIL | No Git remote or GitHub credentials are available in the container. |
| Fresh Windows portable smoke | FAIL | No Git remote or GitHub credentials are available in the container. |
| PR67 description updated | FAIL | GitHub is unavailable; no remote PR body could be changed. |

## Outcome

No browser defect was observed because no browser walkthrough could be run. No
production code or business formulas were changed, and no defect regression was
added. PR8 remains blocked on a real Windows Chrome/Edge walkthrough, fresh
Linux CI, fresh non-skipped Windows portable smoke, and updating the PR67 body.
