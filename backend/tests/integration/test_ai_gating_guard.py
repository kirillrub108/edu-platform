"""Guard: every AI endpoint stays behind a verified-email gate.

Two complementary checks:
  * every entry in AI_GATED_ENDPOINTS resolves to a route that actually depends
    on require_verified_email or require_verified_teacher (catches a gate that
    was removed);
  * every endpoint that enqueues a Celery task — other than infra (send_email)
    and the documented student-grading exclusion — is listed in
    AI_GATED_ENDPOINTS (catches a NEW ungated AI endpoint).

See docs/DECISIONS.md for the gating rationale.
"""

from __future__ import annotations

import inspect
from typing import Any

import pytest
from fastapi.routing import APIRoute

from app.dependencies import (
    AI_GATED_ENDPOINTS,
    require_verified_email,
    require_verified_teacher,
)

pytestmark = pytest.mark.integration

_VERIFIED_GATES = {require_verified_email, require_verified_teacher}
_HTTP_METHODS = {"GET", "POST", "PUT", "PATCH", "DELETE"}
# Celery enqueues that are infrastructure, not gated AI operations.
# process_yookassa_payment settles a paid YooKassa webhook (server-to-server,
# no cookie auth, no AI) — it must NOT be in AI_GATED_ENDPOINTS.
_INFRA_TASKS = ("send_email", "process_yookassa_payment")
# AI Celery endpoints intentionally NOT behind the gate (see docs/DECISIONS.md):
# student quiz grading must work for unverified students.
_EXCLUDED_TASKS = ("grade_attempt_task",)


def _dependency_calls(dependant: Any) -> list[Any]:
    calls: list[Any] = []
    for dep in dependant.dependencies:
        calls.append(dep.call)
        calls.extend(_dependency_calls(dep))
    return calls


def _api_routes(app: Any) -> list[APIRoute]:
    return [r for r in app.routes if isinstance(r, APIRoute)]


def _methods(route: APIRoute) -> set[str]:
    return {m for m in route.methods if m in _HTTP_METHODS}


def test_registered_ai_endpoints_are_gated(app: Any) -> None:
    routes = _api_routes(app)
    for method, path in AI_GATED_ENDPOINTS:
        matches = [r for r in routes if r.path == path and method in _methods(r)]
        assert matches, f"AI_GATED_ENDPOINTS lists {method} {path} but no such route exists"
        gates = set(_dependency_calls(matches[0].dependant)) & _VERIFIED_GATES
        assert gates, f"{method} {path} is registered as AI-gated but has no verified-email gate"


def test_no_ungated_celery_ai_endpoint(app: Any) -> None:
    for route in _api_routes(app):
        try:
            source = inspect.getsource(inspect.unwrap(route.endpoint))
        except (OSError, TypeError):
            continue
        if ".apply_async(" not in source and ".delay(" not in source:
            continue
        if any(t in source for t in _INFRA_TASKS + _EXCLUDED_TASKS):
            continue
        for method in _methods(route):
            assert (method, route.path) in AI_GATED_ENDPOINTS, (
                f"{method} {route.path} enqueues a Celery task but is not in "
                "AI_GATED_ENDPOINTS — gate it with require_verified_email and register it"
            )
