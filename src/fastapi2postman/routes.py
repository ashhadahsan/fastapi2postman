"""Every route an app really serves, and what protects it.

The schema can't answer this. It leaves out routes hidden from the docs, websockets and plain Starlette routes, which
are exactly what a check for open routes has to see, so this reads the routes themselves. Anything it doesn't recognise
is reported as unreadable instead of being skipped, so a change in FastAPI's internals shows up in the audit rather than
hiding routes from it.
"""

import re
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from typing import Any

from fastapi import FastAPI
from fastapi.security.base import SecurityBase
from starlette.routing import Mount, WebSocketRoute

from . import _SECRET

_AUTH_PARAMETER = re.compile(f"{_SECRET.pattern}|authorization|session", re.IGNORECASE)


@dataclass(frozen=True)
class Route:
    method: str  # an HTTP method, WS for a websocket, or * when a mounted app decides
    path: str
    auth: list[str]  # security schemes by name, and required parameters that look like credentials
    tags: list[str]
    hidden: bool  # left out of the docs
    unreadable: str  # the kind of route, when it has no dependencies to read auth from


def _auth(dependant: Any) -> list[str]:
    """What protects a route, from its dependencies at any depth. Only what they declare: their code isn't run."""
    found = []
    if isinstance(dependant.call, SecurityBase):
        optional = not getattr(dependant.call, "auto_error", True)
        found.append(dependant.call.scheme_name + (" (optional)" if optional else ""))
    for parameter in (*dependant.header_params, *dependant.query_params, *dependant.cookie_params):
        if parameter.field_info.is_required() and _AUTH_PARAMETER.search(parameter.alias):
            found.append(parameter.alias)
    for dependency in dependant.dependencies:
        found.extend(_auth(dependency))
    return list(dict.fromkeys(found))


def _flatten(routes: Iterable[Any]) -> Iterator[Any]:
    """The routes behind include_router(), which FastAPI 0.137+ keeps in a private object. Before that they're flat."""
    for route in routes:
        contexts = getattr(route, "effective_route_contexts", None)
        if contexts is None:
            yield route
        else:
            for context in contexts():
                # Websockets, plain routes and mounts come with a ready-made route. API routes are the context itself.
                yield getattr(context, "starlette_route", None) or context


def _walk(routes: Iterable[Any], prefix: str, docs: set[str]) -> Iterator[Route]:
    for route in _flatten(routes):
        if isinstance(route, Mount):
            mounted = prefix + route.path
            if isinstance(route.app, FastAPI):
                yield from _app_routes(route.app, mounted)
            elif route.routes:
                yield from _walk(route.routes, mounted, set())
            else:
                yield Route("*", mounted or "/", [], [], False, type(route.app).__name__)
            continue
        dependant = getattr(route, "dependant", None)
        path = prefix + getattr(route, "path_format", getattr(route, "path", ""))
        if dependant is None and path in docs:
            continue
        for method in getattr(route, "methods", None) or ["WS" if isinstance(route, WebSocketRoute) else "*"]:
            yield Route(
                method=method,
                path=path or "/",
                auth=[] if dependant is None else _auth(dependant),
                tags=[getattr(tag, "value", tag) for tag in getattr(route, "tags", [])],
                hidden=not getattr(route, "include_in_schema", True),
                unreadable=type(route).__name__ if dependant is None else "",
            )


def _app_routes(app: FastAPI, prefix: str) -> Iterator[Route]:
    own_docs = (app.openapi_url, app.docs_url, app.redoc_url, app.swagger_ui_oauth2_redirect_url)
    yield from _walk(app.routes, prefix, {prefix + url for url in own_docs if url})


def list_routes(app: FastAPI) -> list[Route]:
    """Every route the app serves, apart from FastAPI's own docs, sorted by path and then method."""
    return sorted(_app_routes(app, ""), key=lambda route: (route.path, route.method))
