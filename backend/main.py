"""Thin FastAPI transport shell for the local application."""

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend"

app = FastAPI(title="sklad_ozon", docs_url=None, redoc_url=None)


@app.get("/api/health")
def health() -> dict[str, object]:
    return {"status": "ok", "service": "sklad_ozon", "api_version": 1}


@app.get("/", response_class=FileResponse)
def index() -> FileResponse:
    return FileResponse(FRONTEND / "index.html", media_type="text/html")


app.mount("/assets", StaticFiles(directory=FRONTEND / "assets"), name="assets")
