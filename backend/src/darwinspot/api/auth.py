from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Cookie, Depends, Header, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from darwinspot.config import get_settings
from darwinspot.security.sessions import issue_session_token, verify_owner_password
from darwinspot.storage.database import get_db
from darwinspot.storage.models import OwnerSession
from darwinspot.storage.repository import Repository

router = APIRouter(prefix="/api/auth", tags=["auth"])
SESSION_COOKIE = "darwinspot_session"
CSRF_COOKIE = "darwinspot_csrf"
RECENT_REAUTH_WINDOW = timedelta(minutes=15)


class LoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    password: str = Field(min_length=1, max_length=256)


def current_owner(
    session_cookie: str | None = Cookie(default=None, alias=SESSION_COOKIE),
    db: Session = Depends(get_db),
):
    if session_cookie is None:
        raise HTTPException(status_code=401, detail="owner session required")
    owner = Repository(db).get_session(session_cookie)
    if owner is None:
        raise HTTPException(status_code=401, detail="owner session expired or revoked")
    return owner


def require_recent_reauthentication(owner: OwnerSession) -> OwnerSession:
    authenticated_at = owner.created_at
    if authenticated_at.tzinfo is None:
        authenticated_at = authenticated_at.replace(tzinfo=UTC)
    if datetime.now(UTC) - authenticated_at.astimezone(UTC) > RECENT_REAUTH_WINDOW:
        raise HTTPException(status_code=401, detail="recent owner re-authentication required")
    return owner


def mutation_owner(
    request: Request,
    owner: OwnerSession = Depends(current_owner),
    csrf_cookie: str | None = Cookie(default=None, alias=CSRF_COOKIE),
    csrf_header: str | None = Header(default=None, alias="X-DarwinSpot-CSRF"),
):
    origin = request.headers.get("origin")
    if origin is not None and origin != get_settings().frontend_origin:
        raise HTTPException(status_code=403, detail="origin validation failed")
    if csrf_cookie is None or csrf_header != csrf_cookie:
        raise HTTPException(status_code=403, detail="CSRF validation failed")
    return owner


@router.post("/login")
def login(
    request: LoginRequest, response: Response, db: Session = Depends(get_db)
) -> dict[str, str]:
    password_hash = get_settings().owner_password_hash
    if not password_hash or not verify_owner_password(request.password, password_hash):
        raise HTTPException(status_code=401, detail="invalid owner credentials")
    raw_token, _ = issue_session_token()
    Repository(db).create_session(raw_token)
    csrf = issue_session_token()[0]
    secure = get_settings().frontend_origin.startswith("https://")
    response.set_cookie(
        SESSION_COOKIE, raw_token, httponly=True, secure=secure, samesite="lax", max_age=43200
    )
    response.set_cookie(
        CSRF_COOKIE, csrf, httponly=False, secure=secure, samesite="lax", max_age=43200
    )
    return {"status": "authenticated"}


@router.post("/logout")
def logout(
    response: Response,
    owner: OwnerSession = Depends(mutation_owner),
    db: Session = Depends(get_db),
) -> dict[str, str]:
    owner.revoked_at = datetime.now(UTC)
    db.commit()
    response.delete_cookie(SESSION_COOKIE)
    response.delete_cookie(CSRF_COOKIE)
    return {"status": "logged_out"}


@router.get("/me")
def me(owner: OwnerSession = Depends(current_owner)) -> dict[str, str]:
    return {"status": "authenticated", "sessionId": owner.id}
