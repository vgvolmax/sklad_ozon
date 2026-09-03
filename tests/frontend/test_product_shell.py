from pathlib import Path

ROOT = Path(__file__).parents[2]


def test_product_shell_is_local_semantic_and_has_canonical_sections():
    html = (ROOT / "frontend/index.html").read_text()
    assert '<html lang="ru">' in html
    assert 'aria-label="Основные разделы"' in html
    assert '<main id="app-main">' in html
    for section, label in (("plan", "План"), ("flows", "Потоки спроса"), ("economics", "Экономика"), ("data", "Данные")):
        assert f'href="#{section}"' in html
        assert f'data-section="{section}"' in html
        assert label in html
    assert 'id="detail-drawer"' in html
    assert 'id="progress-region" aria-live="polite"' in html
    assert 'id="global-analysis-status"' in html
    for asset in ("/assets/css/app.css", "/assets/js/core.js", "/assets/js/components.js", "/assets/js/app.js"):
        assert asset in html
    lowered = html.lower()
    assert "https://" not in lowered
    assert all(word not in lowered for word in ("react", "vue", "angular", "svelte", "stockout / distortion evidence", "<pre"))


def test_top_navigation_and_brand_use_the_canonical_navigation_controller():
    html = (ROOT / "frontend/index.html").read_text()
    app = (ROOT / "frontend/assets/js/app.js").read_text()
    assert '<a class="brand" href="#plan" data-nav="plan">' in html
    assert "document.querySelectorAll('[data-nav]')" in app
    assert "event.preventDefault()" in app
    assert "navigate(link.dataset.nav)" in app


def test_css_has_accessibility_modes_and_semantic_tokens():
    css = (ROOT / "frontend/assets/css/app.css").read_text()
    assert css.count(":root") == 1
    for token in ("--color-ozon", "--color-model", "--color-warning", "--color-focus", "--page-max"):
        assert token in css
    assert "prefers-reduced-motion:reduce" in css
    assert "forced-colors:active" in css
    assert "overflow-x:hidden" not in css.replace(" ", "")


def test_analysis_busy_state_is_scoped_to_request_affecting_controls():
    app = (ROOT / "frontend/assets/js/app.js").read_text()
    assert "#analysis-form input,#analysis-form select,#analysis-form button[type=submit],#mapping-rows input,#mapping-rows button,#add-mapping,#save-mappings" in app
    assert "analysisActive?'disabled':''" in app
    assert "#plan-search" not in app[app.index("function updateRequestControls"):app.index("function renderMappings")]
