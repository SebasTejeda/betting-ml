"""Dependency injection: the composition root (Container) lives in app.state."""

from __future__ import annotations

from typing import Any

from fastapi import Request


def get_container(request: Request) -> Any:
    return request.app.state.container
