"""Owner login, session inspection, and logout routes."""

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.auth_service import (
    SESSION_COOKIE,
    SESSION_LIFETIME,
    STATE_COOKIE,
    owner_authorization_url,
    revoke_owner_session,
    secure_cookie,
)
from app.database import get_database


router = APIRouter(prefix="/auth", tags=["authentication"])


@router.get("/login", response_class=RedirectResponse)
def login(
    request: Request,
    next: str = "/dashboard",
    database: Session = Depends(get_database),
) -> RedirectResponse:
    url, state = owner_authorization_url(database, next)
    response = RedirectResponse(url=url, status_code=307)
    response.set_cookie(
        STATE_COOKIE,
        state,
        max_age=600,
        httponly=True,
        secure=secure_cookie(request),
        samesite="lax",
        path="/google/oauth",
    )
    return response


@router.get("/session", response_class=JSONResponse)
def session_details(request: Request) -> dict:
    return {"authenticated": True, "email": request.state.owner_email}


@router.post("/logout", response_class=RedirectResponse)
def logout(request: Request, database: Session = Depends(get_database)) -> RedirectResponse:
    revoke_owner_session(database, request.cookies.get(SESSION_COOKIE, ""))
    response = RedirectResponse(url="/auth/login", status_code=303)
    response.delete_cookie(SESSION_COOKIE, path="/")
    return response
