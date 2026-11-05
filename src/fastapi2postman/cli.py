"""The fastapi2postman command."""

import argparse
import json
import os
import sys
import textwrap
from fnmatch import fnmatchcase
from importlib import import_module, metadata
from pathlib import Path

from fastapi import FastAPI

from . import to_postman
from .routes import Route, list_routes

_APP_HELP = "the app: main.py, main.py:api or package.main:api. The name defaults to app, and may be a factory"


def _module_of(path: Path) -> tuple[str, Path]:
    """The dotted name of a file and the folder to import it from, which is above its package if it's in one."""
    parts = [path.stem]
    root = path.parent
    while (root / "__init__.py").is_file():
        parts.insert(0, root.name)
        root = root.parent
    return ".".join(parts), root


def _load_app(spec: str) -> FastAPI:
    target, attribute = spec, "app"
    if ":" in spec and not Path(spec).is_file():  # a colon can be part of a path: C:\project\app.py
        target, attribute = spec.rsplit(":", 1)

    name = target
    search = [os.getcwd()]  # a console script has its own folder on sys.path, not the project's
    if Path(target).is_file():
        name, root = _module_of(Path(target).resolve())
        search.insert(0, str(root))
    sys.path[:0] = search

    try:
        module = import_module(name)
    except ModuleNotFoundError as error:
        if error.name != name and not name.startswith(f"{error.name}."):
            raise  # something the app itself imports is missing, and the traceback says what
        raise SystemExit(
            f"fastapi2postman: cannot find {target!r}: give a .py file, or a module importable from {os.getcwd()}"
        ) from error
    if not hasattr(module, attribute):
        raise SystemExit(f"fastapi2postman: {name} has no attribute {attribute!r}")

    app = getattr(module, attribute)
    if not isinstance(app, FastAPI) and callable(app):
        app = app()  # a factory
    if not isinstance(app, FastAPI):
        raise SystemExit(f"fastapi2postman: {spec} gives {type(app).__name__}, not a FastAPI app")
    return app


def _export(argv: list[str]) -> None:
    parser = argparse.ArgumentParser(
        prog="fastapi2postman",
        description="Turn a FastAPI app into a Postman collection you can run straight away.",
        epilog="other commands: 'routes' lists every route with its auth, and 'audit' fails when a route has no auth. "
        "Add --help to either one for details.",
    )
    parser.add_argument("--app", required=True, help=_APP_HELP)
    parser.add_argument("--output", default="output.json", help="output file (default: %(default)s)")
    parser.add_argument("--name", help="collection name (default: the app's title)")
    parser.add_argument(
        "--base-url", help="where the requests go (default: the app's first server, else http://localhost:8000)"
    )
    parser.add_argument("--host", help="shorthand for --base-url http://HOST:PORT")
    parser.add_argument("--port", type=int, help="shorthand for --base-url http://HOST:PORT")
    parser.add_argument(
        "--bearer",
        action="store_true",
        help="send {{bearerToken}} on every request without auth of its own: for auth in middleware, or in a "
        "dependency reading request.headers, which the app's schema can't show",
    )
    parser.add_argument("--version", action="version", version=metadata.version("fastapi2postman"))
    args = parser.parse_args(argv)

    base_url = args.base_url
    if not base_url and (args.host or args.port):
        base_url = f"http://{args.host or 'localhost'}:{args.port or 8000}"

    collection = to_postman(_load_app(args.app), name=args.name, base_url=base_url, bearer=args.bearer)
    text = json.dumps(collection, indent=2, ensure_ascii=False)
    Path(args.output).write_text(text + "\n", encoding="utf-8")
    count = sum(len(entry.get("item", [entry])) for entry in collection["item"])
    print(f"{args.output}: {count} requests")


def _table(rows: list[list[str]]) -> str:
    widths = [max(len(row[column]) for row in rows) for column in range(len(rows[0]))]
    lines = ["  ".join(cell.ljust(width) for cell, width in zip(row, widths, strict=True)).rstrip() for row in rows]
    return "\n".join(lines)


def _routes(argv: list[str]) -> None:
    parser = argparse.ArgumentParser(
        prog="fastapi2postman routes",
        description="List every route the app serves with what protects it, including routes hidden from the docs.",
    )
    parser.add_argument("--app", required=True, help=_APP_HELP)
    args = parser.parse_args(argv)

    rows = [["METHOD", "PATH", "AUTH", "TAGS", "NOTE"]]
    for route in list_routes(_load_app(args.app)):
        auth = ", ".join(route.auth) or ("?" if route.unreadable else "-")
        note = f"can't read: {route.unreadable}" if route.unreadable else "hidden from the docs" if route.hidden else ""
        rows.append([route.method, route.path, auth, ", ".join(route.tags) or "-", note])
    print(_table(rows))


def _allows(pattern: str, route: Route) -> bool:
    return fnmatchcase(f"{route.method} {route.path}" if " " in pattern else route.path, pattern)


def _audit(argv: list[str]) -> None:
    parser = argparse.ArgumentParser(
        prog="fastapi2postman audit",
        description="Fail when a route has no visible auth, including routes hidden from the docs. It reads what the "
        "routes declare and doesn't run them, so it can't see auth in middleware, or what a dependency's code does.",
    )
    parser.add_argument("--app", required=True, help=_APP_HELP)
    parser.add_argument(
        "--allow",
        action="append",
        default=[],
        metavar="PATTERN",
        help='a route meant to be open, such as "/health" or "GET /public/*". Repeat it for more',
    )
    args = parser.parse_args(argv)

    routes = list_routes(_load_app(args.app))
    for pattern in args.allow:
        if not any(_allows(pattern, route) for route in routes):
            print(f"fastapi2postman: --allow {pattern!r} matches no route", file=sys.stderr)

    unprotected = [route for route in routes if not route.auth]
    flagged = [route for route in unprotected if not any(_allows(pattern, route) for pattern in args.allow)]
    if not flagged:
        with_auth = len(routes) - len(unprotected)
        print(f"{len(routes)} routes: {with_auth} with auth, {len(unprotected)} allowed")
        return

    rows = []
    for route in flagged:
        why = f"can't read: {route.unreadable}" if route.unreadable else "no auth"
        rows.append([route.method, route.path, why + (", hidden from the docs" if route.hidden else "")])
    print(f"{len(flagged)} of {len(routes)} routes have no visible auth:\n")
    print(textwrap.indent(_table(rows), "  "))
    print(
        '\nProtect them, or allow the ones meant to be open, for example --allow "/health" or --allow "GET /public/*".'
    )
    raise SystemExit(1)


def main() -> None:
    commands = {"routes": _routes, "audit": _audit}
    argv = sys.argv[1:]
    if argv and argv[0] in commands:
        commands[argv[0]](argv[1:])
    else:
        _export(argv)
