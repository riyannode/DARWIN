from __future__ import annotations

import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from darwinspot.api import activity, agent, auth, portfolio
from darwinspot.config import get_settings
from darwinspot.storage.database import SessionLocal
from darwinspot.storage.repository import Repository

logging.basicConfig(
    level=getattr(logging, get_settings().log_level.upper(), logging.INFO),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
app = FastAPI(title="DarwinSpot API", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[get_settings().frontend_origin],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT"],
    allow_headers=["Content-Type", "X-DarwinSpot-CSRF"],
)
app.include_router(auth.router)
app.include_router(agent.router)
app.include_router(portfolio.router)
app.include_router(activity.router)


@app.get("/health/live")
def live() -> dict[str, str]:
    return {"status": "alive"}


@app.get("/health/ready")
def ready() -> dict[str, str]:
    settings = get_settings()
    with SessionLocal() as db:
        mode = Repository(db).get_or_create_agent().mode
        missing_human_auth = mode == "HUMAN_APPROVAL" and not settings.token_encryption_key
        if not settings.owner_password_hash or not settings.openai_api_key or missing_human_auth:
            from fastapi import HTTPException

            raise HTTPException(status_code=503, detail="required backend configuration is missing")
        db.execute(text("SELECT 1"))
    return {"status": "ready"}
