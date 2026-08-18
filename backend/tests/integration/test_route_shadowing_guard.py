"""Guard: no two routes silently shadow each other.

FastAPI/Starlette match routes by registration order — if two routers declare
the same (method, path), the one registered first in main.py wins and the
second is silently dead code, whatever guard it carries. This bit for real:
lessons.py and quiz_teacher.py both declared GET /{lesson_id}/quiz/questions,
lessons.py registered first with only `get_current_user`, and the properly
owner-scoped copy in quiz_teacher.py never ran — any authenticated user could
read quiz answer keys. See docs/DECISIONS.md and the fix that removed the
duplicate from lessons.py.

This test enumerates every real APIRoute FastAPI mounted and fails if any
(method, normalized path) is claimed by more than one route object, so a new
duplicate is caught at test time instead of in production traffic.
"""

from __future__ import annotations

import re
from collections import defaultdict
from typing import Any

import pytest
from fastapi.routing import APIRoute

pytestmark = pytest.mark.integration

_HTTP_METHODS = {"GET", "POST", "PUT", "PATCH", "DELETE"}
# Path params are an implementation detail of naming (e.g. {lesson_id} vs
# {id}) — two routes differing only in param name still collide at request
# time, so we fold every {...} segment to a single placeholder before keying.
_PARAM_RE = re.compile(r"\{[^}]+\}")


def _api_routes(app: Any) -> list[APIRoute]:
    return [r for r in app.routes if isinstance(r, APIRoute)]


def _methods(route: APIRoute) -> set[str]:
    return {m for m in route.methods if m in _HTTP_METHODS}


def _normalized_path(path: str) -> str:
    return _PARAM_RE.sub("{}", path)


def _label(route: APIRoute) -> str:
    endpoint = route.endpoint
    return f"{endpoint.__module__}.{endpoint.__name__}"


def test_no_duplicate_registered_routes(app: Any) -> None:
    by_key: dict[tuple[str, str], list[APIRoute]] = defaultdict(list)
    for route in _api_routes(app):
        norm_path = _normalized_path(route.path)
        for method in _methods(route):
            by_key[(method, norm_path)].append(route)

    for (method, norm_path), routes in by_key.items():
        # Same route object can appear for multiple methods on one decorator;
        # what we care about is >1 DISTINCT route claiming this (method, path).
        distinct = {id(r): r for r in routes}
        if len(distinct) <= 1:
            continue
        labels = sorted({_label(r) for r in distinct.values()})
        paths = sorted({r.path for r in distinct.values()})
        pytest.fail(
            f"{method} {norm_path} is registered by {len(distinct)} routes — "
            f"one will silently shadow the other(s) at request time.\n"
            f"  concrete paths: {paths}\n"
            f"  registered by: {labels}"
        )
