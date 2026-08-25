import re
from pathlib import Path


ROOT = Path(__file__).parents[1]


def runtime_frontend_files():
    yield ROOT / "frontend" / "index.html"
    yield from sorted((ROOT / "frontend" / "assets").rglob("*.css"))
    yield from sorted((ROOT / "frontend" / "assets").rglob("*.js"))


def test_runtime_frontend_has_no_external_asset_or_request_urls():
    html = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")
    urls = re.findall(r"(?:src|href)\s*=\s*['\"]([^'\"]+)", html, re.I)
    for css in (ROOT / "frontend" / "assets").rglob("*.css"):
        text = css.read_text(encoding="utf-8")
        urls.extend(re.findall(r"url\(\s*['\"]?([^'\")\s]+)", text, re.I))
        urls.extend(re.findall(r"@import\s+(?:url\()?\s*['\"]([^'\"]+)", text, re.I))
    for javascript in (ROOT / "frontend" / "assets").rglob("*.js"):
        text = javascript.read_text(encoding="utf-8")
        urls.extend(re.findall(r"(?:fetch|WebSocket|EventSource)\s*\(\s*['\"]([^'\"]+)", text))

    external = [url for url in urls if re.match(r"^(?:https?:)?//", url, re.I)]
    assert external == []


def test_release_frontend_files_are_committed_and_local():
    files = list(runtime_frontend_files())
    assert ROOT / "frontend" / "index.html" in files
    assert ROOT / "frontend" / "assets" / "css" / "app.css" in files
    assert ROOT / "frontend" / "assets" / "js" / "app.js" in files
    assert all(path.is_file() for path in files)


def test_start_script_has_fail_closed_repair_and_data_preservation_contract():
    script = (ROOT / "start.bat").read_text(encoding="utf-8")
    lowered = script.lower()
    assert "startup_status.json" in script
    assert "RUNTIME_REPAIR_REQUIRED" in script
    assert "runtime_valid" in lowered
    assert "connect to the internet" in lowered
    assert "run start.bat again" in lowered
    assert "data" in lowered and "preserved" in lowered
    assert 'if not exist "%root%data" mkdir "%root%data"' in lowered
    assert "set path=" not in lowered
    assert "where python" not in lowered
    assert 'rmdir /s /q "%root%data' not in lowered
    assert not re.search(r'(?im)^\s*(?:python|python3|py)(?:\.exe)?\s', script)
