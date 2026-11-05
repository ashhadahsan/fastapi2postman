import argparse
import json
import os
import sys
import importlib
from fastapi.routing import APIRoute


def register_routes(app):
    routes = []
    for route in app.routes:
        if isinstance(route, APIRoute):
            routes.append(
                {
                    "name": route.name,
                    "method": ",".join(route.methods),
                    "url": str(route.path),
                    "path": str(route.path).replace("{", ":").replace("}", ""),
                }
            )
    return routes


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=str, help="Output file", default="output.json")
    parser.add_argument(
        "--name", type=str, help="Collection name", default="FastAPI API"
    )
    parser.add_argument("--host", type=str, help="API host", default="localhost")
    parser.add_argument("--port", type=int, help="API port", default=8000)
    parser.add_argument(
        "--app",
        type=str,
        help="Path to FastAPI application instance; can be a .py file or module:attribute",
        default="app.py",
        required=True,
    )
    args = parser.parse_args()

    app_path = args.app

    if os.path.isfile(app_path) and app_path.endswith(".py"):
        app_dir, app_file = os.path.split(app_path)
        sys.path.append(app_dir or ".")
        app_name, _ = os.path.splitext(app_file)
        module = __import__(app_name)
        app = getattr(module, "app")

    elif ":" in app_path:
        module_name, attr = app_path.split(":", 1)
        module = importlib.import_module(module_name)
        app = getattr(module, attr)
    else:
        parser.error(
            "--app must be a Python file (.py) or module:attribute format"
        )
        return

    routes = register_routes(app)
    collection = {
        "info": {
            "name": args.name,
            "schema": "https://schema.getpostman.com/json/collection/v2.1.0/collection.json",
        },
        "item": [],
    }

    for route in routes:
        item = {
            "name": route["name"],
            "request": {
                "url": f'http://{args.host}:{args.port}{route["url"]}',
                "method": route["method"],
            },
        }
        collection["item"].append(item)

    with open(args.output, "w") as f:
        json.dump(collection, f, indent=4)


if __name__ == "__main__":
    main()
