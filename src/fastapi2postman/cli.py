"""The fastapi2postman command."""

import argparse
import json
import os
import sys
from importlib import import_module, metadata
from pathlib import Path

from fastapi import FastAPI

from . import to_postman


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


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="fastapi2postman", description="Turn a FastAPI app into a Postman collection you can run straight away."
    )
    parser.add_argument(
        "--app",
        required=True,
        help="the app: main.py, main.py:api or package.main:api. The name defaults to app, and may be a factory",
    )
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
    args = parser.parse_args()

    base_url = args.base_url
    if not base_url and (args.host or args.port):
        base_url = f"http://{args.host or 'localhost'}:{args.port or 8000}"

    collection = to_postman(_load_app(args.app), name=args.name, base_url=base_url, bearer=args.bearer)
    text = json.dumps(collection, indent=2, ensure_ascii=False)
    Path(args.output).write_text(text + "\n", encoding="utf-8")
    count = sum(len(entry.get("item", [entry])) for entry in collection["item"])
    print(f"{args.output}: {count} requests")
