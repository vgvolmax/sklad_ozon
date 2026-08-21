import json

import pytest

import launcher


HEALTH = {"status": "ok", "service": "sklad_ozon", "api_version": 1}


def test_invalid_utf8_health_is_treated_as_foreign(monkeypatch):
    class Response:
        status = 200
        def __enter__(self): return self
        def __exit__(self, *_args): return False
        def read(self): return b"\xff"
    monkeypatch.setattr(launcher.urllib.request, "urlopen", lambda *_a, **_k: Response())
    assert launcher.fetch_health() is None


def test_existing_valid_server_is_reused(monkeypatch, tmp_path):
    started, opened = [], []
    monkeypatch.setattr(launcher, "DATA_DIR", tmp_path)
    monkeypatch.setattr(launcher, "fetch_health", lambda: HEALTH)
    monkeypatch.setattr(launcher, "start_server_wrapper", lambda: started.append(1))
    monkeypatch.setattr(launcher, "open_browser", lambda: opened.append(1))
    assert launcher.launch() == 0
    assert started == [] and opened == [1]


def test_free_port_starts_detached_server_and_never_stops_it(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(launcher, "DATA_DIR", tmp_path)
    monkeypatch.setattr(launcher, "fetch_health", lambda: None)
    monkeypatch.setattr(launcher, "port_is_open", lambda: False)
    monkeypatch.setattr(launcher, "start_server_wrapper", lambda: calls.append("start"))
    monkeypatch.setattr(launcher, "wait_until_ready", lambda: True)
    monkeypatch.setattr(launcher, "open_browser", lambda: calls.append("browser"))
    assert launcher.launch() == 0
    assert calls == ["start", "browser"]
    assert not hasattr(launcher, "stop_server")


def test_readiness_failure_does_not_open_browser(monkeypatch, tmp_path):
    opened = []
    monkeypatch.setattr(launcher, "DATA_DIR", tmp_path)
    monkeypatch.setattr(launcher, "fetch_health", lambda: None)
    monkeypatch.setattr(launcher, "port_is_open", lambda: False)
    monkeypatch.setattr(launcher, "start_server_wrapper", lambda: None)
    monkeypatch.setattr(launcher, "wait_until_ready", lambda: False)
    monkeypatch.setattr(launcher, "open_browser", lambda: opened.append(1))
    assert launcher.launch() == 1
    assert opened == []
    assert json.loads((tmp_path / "startup_status.json").read_text())["status"] == "error"


def test_foreign_port_fails_without_start_or_browser(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(launcher, "DATA_DIR", tmp_path)
    monkeypatch.setattr(launcher, "fetch_health", lambda: {"status": "foreign"})
    monkeypatch.setattr(launcher, "port_is_open", lambda: True)
    monkeypatch.setattr(launcher, "start_server_wrapper", lambda: calls.append("start"))
    monkeypatch.setattr(launcher, "open_browser", lambda: calls.append("browser"))
    assert launcher.launch() == 1
    assert calls == []
    status = json.loads((tmp_path / "startup_status.json").read_text())
    assert "17843" in status["message"]
