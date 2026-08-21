from pathlib import Path


ROOT = Path(__file__).parents[1]


def test_runtime_versions_are_exactly_pinned():
    assert (ROOT / "requirements.txt").read_text().splitlines() == [
        "fastapi==0.139.2", "uvicorn==0.51.0", "openpyxl==3.1.5",
        "python-multipart==0.0.32",
    ]
    assert (ROOT / "requirements-dev.txt").read_text().splitlines() == [
        "-r requirements.txt", "pytest==8.4.2", "httpx==0.28.1",
    ]


def test_start_script_uses_local_runtime_and_isolates_data():
    script = (ROOT / "start.bat").read_text().lower()
    assert "runtime\\python.exe" in script
    assert "3.13.14" in script
    assert "python.org" in script and ".part" in script
    assert "requirements.txt" in script
    assert "launcher.py" in script
    assert "set path=" not in script
    assert "where python" not in script
    assert "rmdir /s /q \"%root%data" not in script
    assert "runtime_valid" in script
    assert "rmdir /s /q \"%runtime%\"" in script


def test_runtime_and_data_are_ignored_separately():
    ignored = (ROOT / ".gitignore").read_text().splitlines()
    assert "/runtime/" in ignored
    assert "/data/" in ignored
