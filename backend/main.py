"""DataSentry FastAPI application.

Run:  uvicorn main:app --reload --port 8000   (from the backend/ directory)
Docs: http://localhost:8000/docs
"""
from __future__ import annotations

import json
import logging
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

import config
from api.routes import VERSION, router
from core import database as db
from core.experiment_service import service


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {"ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S"), "level": record.levelname,
                   "logger": record.name, "msg": record.getMessage()}
        for key in ("method", "path", "status", "duration_ms"):
            if hasattr(record, key):
                payload[key] = getattr(record, key)
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload)


def setup_logging() -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(logging.INFO)
    for noisy in ("web3", "urllib3", "uvicorn.access"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


setup_logging()
log = logging.getLogger("datasentry")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    config.ensure_dirs()
    db.init_db()
    # mark experiments interrupted by a previous shutdown
    db.execute("UPDATE experiment_results SET status = 'interrupted' WHERE status = 'running'")
    try:
        service.bootstrap_clients()
    except Exception as e:  # blockchain may be offline; the API still serves data
        log.warning("client bootstrap incomplete: %s", e)
    log.info("DataSentry API ready (blockchain=%s)", service.chain.status()["connected"])
    yield


app = FastAPI(
    title="DataSentry API",
    version=VERSION,
    description="Blockchain-protected collaborative AI platform: federated learning, AI poisoning "
                "detection, trust scoring and an on-chain audit trail.",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=config.CORS_ORIGINS,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def access_log(request: Request, call_next):
    start = time.perf_counter()
    response = await call_next(request)
    if not request.url.path.endswith("/training/status"):  # avoid flooding logs with polling
        log.info("request", extra={"method": request.method, "path": request.url.path,
                                   "status": response.status_code,
                                   "duration_ms": round((time.perf_counter() - start) * 1000, 1)})
    return response


@app.exception_handler(Exception)
async def unhandled(_request: Request, exc: Exception):
    log.exception("unhandled error")
    return JSONResponse(status_code=500, content={"detail": f"internal error: {exc}"})


app.include_router(router)


@app.get("/", include_in_schema=False)
def root():
    return {"name": "DataSentry", "tagline": "Train Together. Share Nothing. Trust Everything.", "docs": "/docs"}
