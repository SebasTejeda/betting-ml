"""Spec-003 owner login: session cookie (HttpOnly, SameSite=Strict, Secure in prod) + CSRF token."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Request, Response

from betting_ml.api.dependencies import ServicesApi, get_services
from betting_ml.api.errors import ApiError
from betting_ml.api.schemas_auth import LoginIn, LoginOut, MeOut
from betting_ml.api.security import (
    SESSION_COOKIE,
    client_ip,
    public,
    require_read,
    require_write,
)
from betting_ml.application.authenticate import Authenticate
from betting_ml.domain.security import Principal
from betting_ml.logging_config import security_event

PREFIX = "/api/v1/auth"
login_router = APIRouter(prefix=PREFIX, tags=["auth"], dependencies=[Depends(public)])
reads = APIRouter(prefix=PREFIX, tags=["auth"], dependencies=[Depends(require_read)])
writes = APIRouter(prefix=PREFIX, tags=["auth"], dependencies=[Depends(require_write)])


def get_auth(services: ServicesApi = Depends(get_services)) -> Authenticate:
    if services.auth is None:
        raise ApiError(503, "LOGIN_DISABLED", "Login no configurado")
    return services.auth


@login_router.post("/login", response_model=LoginOut)
def login(
    body: LoginIn,
    request: Request,
    response: Response,
    auth: Authenticate = Depends(get_auth),
    services: ServicesApi = Depends(get_services),
) -> LoginOut:
    client = client_ip(request.scope)
    result = auth.login(
        body.password, current_token=request.cookies.get(SESSION_COOKIE), client=client
    )
    security_event("LOGIN_OK", logging.INFO, client=client)
    response.set_cookie(
        SESSION_COOKIE,
        result.token,
        max_age=int(auth.max_age.total_seconds()),
        path="/",
        httponly=True,
        samesite="strict",
        secure=services.secure_cookies,
    )
    return LoginOut(
        csrf_token=result.session.csrf_token,
        expires_at=result.session.expires_at,
        idle_minutes=int(auth.idle.total_seconds() // 60),
    )


@reads.get("/me", response_model=MeOut)
def me(principal: Principal = Depends(require_read)) -> MeOut:
    session = principal.session
    return MeOut(
        authenticated=True,
        kind=principal.kind.value,  # type: ignore[arg-type]
        csrf_token=None if session is None else session.csrf_token,
        expires_at=None if session is None else session.expires_at,
    )


@writes.post("/logout", status_code=204)
def logout(
    request: Request,
    services: ServicesApi = Depends(get_services),
) -> Response:
    token = request.cookies.get(SESSION_COOKIE)
    if token and services.auth is not None:
        services.auth.logout(token)
        security_event("LOGOUT", logging.INFO, client=client_ip(request.scope))
    response = Response(status_code=204)
    response.delete_cookie(
        SESSION_COOKIE, path="/", httponly=True, samesite="strict", secure=services.secure_cookies
    )
    return response
