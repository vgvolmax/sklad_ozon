"""Start or reuse the local sklad_ozon service, then open its UI."""

from __future__ import annotations

import json
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
HOST = "127.0.0.1"
PORT = 17843
BASE_URL = f"http://{HOST}:{PORT}"
HEALTH_URL = f"{BASE_URL}/api/health"


def expected_health(payload: Any) -> bool:
    return payload == {"status": "ok", "service": "sklad_ozon", "api_version": 1}


def fetch_health(timeout: float = 1.0) -> Any | None:
    try:
        with urllib.request.urlopen(HEALTH_URL, timeout=timeout) as response:
            if response.status != 200:
                return None
            return json.loads(response.read().decode("utf-8"))
    except (OSError, urllib.error.URLError, UnicodeDecodeError, json.JSONDecodeError):
        return None


def port_is_open(timeout: float = 0.25) -> bool:
    with socket.socket() as connection:
        connection.settimeout(timeout)
        return connection.connect_ex((HOST, PORT)) == 0


def start_server_wrapper() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    log = (DATA_DIR / "server_console.log").open("ab")
    flags = 0
    if sys.platform == "win32":
        flags = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS
    subprocess.Popen(
        ["cmd.exe", "/d", "/c", str(ROOT / "RUN_SERVER.cmd")],
        cwd=ROOT,
        stdin=subprocess.DEVNULL,
        stdout=log,
        stderr=subprocess.STDOUT,
        creationflags=flags,
        close_fds=True,
    )


def wait_until_ready(timeout: float = 30.0, interval: float = 0.25) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if expected_health(fetch_health()):
            return True
        time.sleep(interval)
    return False


def open_browser() -> None:
    webbrowser.open(BASE_URL, new=2)


def _write_status(status: str, message: str) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    (DATA_DIR / "startup_status.json").write_text(
        json.dumps({"status": status, "message": message}, ensure_ascii=False),
        encoding="utf-8",
    )


def launch() -> int:
    if expected_health(fetch_health()):
        _write_status("ok", "Reused the running sklad_ozon service.")
        open_browser()
        return 0
    if port_is_open():
        message = f"Port {PORT} is occupied by another process; nothing was started."
        _write_status("error", message)
        print(message, file=sys.stderr)
        return 1
    try:
        start_server_wrapper()
    except OSError as error:
        _write_status("error", f"Could not start local server: {error}")
        return 1
    if not wait_until_ready():
        _write_status("error", "Local server did not become healthy before timeout.")
        return 1
    _write_status("ok", "Local server is ready.")
    open_browser()
    return 0


if __name__ == "__main__":
    raise SystemExit(launch())
