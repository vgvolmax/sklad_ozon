"""Cross-layer safety gates for the final Product Completion presentation."""
from pathlib import Path

ROOT = Path(__file__).parents[2]


def test_product_frontend_consumes_snapshot_without_business_calculators_or_pii():
    sources = "\n".join((ROOT / "frontend/assets/js" / name).read_text()
                        for name in ("core.js", "components.js", "flow.js", "app.js"))
    assert "result.snapshot" in sources
    for legacy in ("data.placements", "data.allocations", "data.safe_allocations",
                   "data.logistics", "data.economics"):
        assert legacy not in sources
    for calculator in ("calculateNeed", "calculateMargin", "calculateRouteEconomics",
                       "allocateStock", "forecastDemand"):
        assert calculator not in sources
    for pii in ("buyer", "customer", "phone", "email", "raw order rows"):
        assert pii not in sources.lower()


def test_all_runtime_assets_are_part_of_shell_ci_and_windows_acceptance():
    html = (ROOT / "frontend/index.html").read_text()
    ci = (ROOT / ".github/workflows/ci.yml").read_text()
    windows = (ROOT / "tests/windows/portable-smoke.ps1").read_text()
    assets = ("core.js", "components.js", "flow.js", "app.js")
    positions = [html.index(f'/assets/js/{name}') for name in assets]
    assert positions == sorted(positions)
    for name in assets:
        assert f"node --check frontend/assets/js/{name}" in ci
        assert f'/assets/js/{name}' in windows
