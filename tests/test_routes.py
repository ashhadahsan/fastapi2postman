"""Every route an app serves, including what its schema leaves out, and what protects each one."""

from enum import Enum
from typing import Annotated, Any

import pytest
from fastapi import APIRouter, Cookie, Depends, FastAPI, Form, Header, WebSocket
from fastapi.security import APIKeyCookie, HTTPBearer
from fastapi.staticfiles import StaticFiles
from sample_app import admin, current_user
from sample_app import app as sample
from starlette.applications import Starlette
from starlette.routing import BaseRoute, Mount
from starlette.routing import Route as PlainRoute

from fastapi2postman.routes import Route, list_routes


def found(app: Any) -> dict[tuple[str, str], Route]:
    return {(route.method, route.path): route for route in list_routes(app)}


SAMPLE = found(sample)


def noop() -> None: ...


async def plain_endpoint(request: Any) -> None: ...


async def plain_socket(websocket: Any) -> None: ...


def test_finds_every_route_in_the_schema():
    in_schema = {
        (method.upper(), prefix + path)
        for prefix, app in (("", sample), ("/admin", admin))
        for path, operations in app.openapi()["paths"].items()
        for method in operations
    }
    assert in_schema
    assert in_schema <= set(SAMPLE)


def test_routes_are_sorted_by_path_then_method():
    keys = [(route.path, route.method) for route in list_routes(sample)]
    assert keys == sorted(keys)


@pytest.mark.parametrize(
    ("path", "auth"),
    [
        ("/secured/bearer", ["HTTPBearer"]),
        ("/secured/jwt", ["JWTBearer"]),  # a subclass, under its own name
        ("/secured/user", ["OAuth2PasswordBearer"]),  # inside Depends(current_user)
        ("/secured/admin", ["OAuth2PasswordBearer"]),  # one level further down
        ("/secured/scoped", ["OAuth2PasswordBearer"]),  # Security(oauth2, scopes=[...])
        ("/secured/basic", ["HTTPBasic"]),
        ("/secured/header-key", ["APIKeyHeader"]),
        ("/secured/query-key", ["APIKeyQuery"]),
        ("/secured/both", ["OAuth2PasswordBearer", "APIKeyHeader"]),
        ("/secured/authorization-header", ["authorization"]),  # a dependency reading the header itself
        ("/secured/custom-header", ["x-token"]),
        ("/secured/query-token", ["token"]),
        ("/reports", ["OAuth2PasswordBearer"]),  # APIRouter(dependencies=[...])
        ("/audit", ["OAuth2PasswordBearer"]),  # include_router(router, dependencies=[...])
        ("/admin/stats", ["APIKeyHeader"]),  # a mounted app
    ],
)
def test_auth_is_found_through_depends(path: str, auth: list[str]):
    assert SAMPLE["GET", path].auth == auth


def test_auth_from_dependencies_on_the_whole_app():
    guarded = FastAPI(dependencies=[Depends(current_user)])
    guarded.get("/x")(noop)
    assert found(guarded)["GET", "/x"].auth == ["OAuth2PasswordBearer"]


def test_a_public_route_has_no_auth():
    assert SAMPLE["GET", "/ping"].auth == []
    assert SAMPLE["POST", "/ping"].auth == []


def test_auth_declared_twice_is_listed_once():
    key = HTTPBearer()
    router = APIRouter(dependencies=[Depends(key)])
    router.get("/x", dependencies=[Depends(key)])(noop)
    app = FastAPI(dependencies=[Depends(key)])
    app.include_router(router)
    assert found(app)["GET", "/x"].auth == ["HTTPBearer"]


def test_a_scheme_that_lets_anonymous_requests_through_says_so():
    # Only the dependency's own code can reject a request here, and that can't be read.
    app = FastAPI()
    app.get("/x", dependencies=[Depends(HTTPBearer(auto_error=False))])(noop)
    assert found(app)["GET", "/x"].auth == ["HTTPBearer (optional)"]


def test_cookie_auth():
    app = FastAPI()

    @app.get("/scheme", dependencies=[Depends(APIKeyCookie(name="sid"))])
    def scheme() -> None: ...

    @app.get("/parameter")
    def parameter(session_id: Annotated[str, Cookie()]) -> None: ...

    routes = found(app)
    assert routes["GET", "/scheme"].auth == ["APIKeyCookie"]
    assert routes["GET", "/parameter"].auth == ["session_id"]


def test_what_is_not_auth():
    app = FastAPI()

    @app.get("/optional-token")
    def optional_token(page_token: str | None = None) -> None: ...

    @app.get("/optional-header")
    def optional_header(authorization: Annotated[str | None, Header()] = None) -> None: ...

    @app.get("/tokens/{token_id}")
    def path_parameter(token_id: str) -> None: ...

    @app.post("/login")
    def form_field(password: Annotated[str, Form()]) -> None: ...

    @app.get("/books")
    def lookalike(author: str, q: str) -> None: ...

    assert {path: route.auth for (_, path), route in found(app).items()} == {
        "/optional-token": [],
        "/optional-header": [],
        "/tokens/{token_id}": [],
        "/login": [],
        "/books": [],
    }


def test_hidden_routes_are_found_with_their_auth():
    assert SAMPLE["GET", "/hidden"].hidden is True
    assert SAMPLE["GET", "/hidden"].auth == []
    assert SAMPLE["GET", "/ping"].hidden is False

    app = FastAPI()
    inner = APIRouter(prefix="/inner", dependencies=[Depends(current_user)])
    inner.get("/route-flag", include_in_schema=False)(noop)
    outer = APIRouter(prefix="/outer")
    outer.include_router(inner)
    app.include_router(outer)
    quiet = APIRouter(prefix="/quiet", include_in_schema=False)
    quiet.get("/router-flag")(noop)
    app.include_router(quiet)
    loud = APIRouter(prefix="/loud")
    loud.get("/include-flag")(noop)
    app.include_router(loud, include_in_schema=False)
    routes = found(app)
    assert routes["GET", "/outer/inner/route-flag"].hidden is True
    assert routes["GET", "/outer/inner/route-flag"].auth == ["OAuth2PasswordBearer"]
    assert routes["GET", "/quiet/router-flag"].hidden is True
    assert routes["GET", "/loud/include-flag"].hidden is True


def test_a_mounted_app_hidden_from_the_docs_is_found():
    internal = FastAPI(openapi_url=None)
    internal.get("/dump")(noop)
    app = FastAPI()
    app.mount("/internal", internal)
    assert found(app)["GET", "/internal/dump"].auth == []


@pytest.mark.parametrize("path", ["/docs", "/redoc", "/openapi.json", "/docs/oauth2-redirect", "/admin/docs"])
def test_fastapis_own_docs_routes_are_left_out(path: str):
    assert ("GET", path) not in SAMPLE


def test_docs_at_a_custom_path_are_left_out():
    assert list_routes(FastAPI(docs_url="/help", redoc_url=None, openapi_url="/schema.json")) == []


def test_paths_are_shown_without_converters():
    assert ("GET", "/items/{item_id}/files/{name}") in SAMPLE


def test_tags_including_enums():
    class Tag(Enum):
        shop = "shop"

    app = FastAPI()
    router = APIRouter(tags=["router"])
    router.get("/x", tags=[Tag.shop])(noop)
    app.include_router(router)
    assert found(app)["GET", "/x"].tags == ["router", "shop"]
    assert SAMPLE["GET", "/ping"].tags == []


def test_websockets_with_their_auth():
    app = FastAPI()

    @app.websocket("/open")
    async def open_socket(websocket: WebSocket) -> None: ...

    @app.websocket("/guarded", dependencies=[Depends(current_user)])
    async def guarded(websocket: WebSocket) -> None: ...

    router = APIRouter(prefix="/router")

    @router.websocket("/included")
    async def included(websocket: WebSocket) -> None: ...

    app.include_router(router, dependencies=[Depends(current_user)])
    routes = found(app)
    assert routes["WS", "/open"].auth == []
    assert routes["WS", "/open"].unreadable == ""
    assert routes["WS", "/guarded"].auth == ["OAuth2PasswordBearer"]
    assert routes["WS", "/router/included"].auth == ["OAuth2PasswordBearer"]


def test_plain_routes_cannot_be_read():
    app = FastAPI()
    app.add_route("/plain", plain_endpoint, methods=["POST"])
    app.router.add_websocket_route("/plain-socket", plain_socket)
    router = APIRouter()  # a router's own prefix only applies to its API routes, so it goes on the include here
    router.add_route("/included", plain_endpoint, methods=["POST"])
    router.add_websocket_route("/included-socket", plain_socket)
    app.include_router(router, prefix="/router")
    routes = found(app)
    assert routes["POST", "/plain"].unreadable == "Route"
    assert routes["WS", "/plain-socket"].unreadable == "WebSocketRoute"
    assert routes["POST", "/router/included"].unreadable == "Route"
    assert routes["WS", "/router/included-socket"].unreadable == "WebSocketRoute"


def test_a_mounted_app_without_routes_cannot_be_read():
    app = FastAPI()
    app.mount("/static", StaticFiles(directory=".", check_dir=False))
    assert found(app)["*", "/static"].unreadable == "StaticFiles"


def test_routes_inside_a_mounted_starlette_app_are_listed():
    app = FastAPI()
    app.mount("/legacy", Starlette(routes=[PlainRoute("/x", plain_endpoint, methods=["POST"])]))
    assert found(app)["POST", "/legacy/x"].unreadable == "Route"


def test_a_router_with_mounted_routes():
    router = APIRouter(prefix="/router")
    router.routes.append(Mount("/files", app=StaticFiles(directory=".", check_dir=False)))
    app = FastAPI()
    app.include_router(router)
    # Old FastAPI drops mounts on include_router(), so the route may be gone but must never pass as protected.
    assert all(route.unreadable for route in list_routes(app))


def test_an_unknown_kind_of_route_is_reported_not_skipped():
    # If FastAPI changes its internals again, this is what must show up instead of routes silently going missing.
    class NewKindOfRoute(BaseRoute):
        pass

    app = FastAPI()
    app.router.routes.append(NewKindOfRoute())
    assert found(app)["*", "/"].unreadable == "NewKindOfRoute"
