"""Turn a FastAPI app into a Postman collection you can run straight away."""

import json
import re
from collections.abc import Iterator
from typing import Any
from urllib.parse import urljoin, urlsplit

from fastapi import FastAPI
from starlette.routing import Mount

__all__ = ["to_postman"]

Json = dict[str, Any]

_METHODS = {"get", "put", "post", "delete", "options", "head", "patch", "trace"}
_FORM_MODES = {"application/x-www-form-urlencoded": "urlencoded", "multipart/form-data": "formdata"}
# Parameters with these names hold a blank variable: the real value must never end up in a collection people share.
_SECRET = re.compile(r"token|api[-_]?key|secret|password", re.IGNORECASE)
_BEARER = {"type": "bearer", "bearer": [{"key": "token", "value": "{{bearerToken}}", "type": "string"}]}
_BASIC = {
    "type": "basic",
    "basic": [
        {"key": "username", "value": "{{username}}", "type": "string"},
        {"key": "password", "value": "{{password}}", "type": "string"},
    ],
}
_FORMATS = {
    "date": "2026-01-01",
    "date-time": "2026-01-01T00:00:00Z",
    "duration": "P1D",
    "email": "user@example.com",
    "ipv4": "127.0.0.1",
    "ipv6": "::1",
    "time": "00:00:00",
    "uri": "https://example.com/",
    "uuid": "00000000-0000-4000-8000-000000000000",
    "uuid4": "00000000-0000-4000-8000-000000000000",
}


def _compact(values: Json) -> Json:
    return {key: value for key, value in values.items() if value}


def _resolve(schema: Json, spec: Json) -> Json:
    if "$ref" not in schema:
        return schema
    target = spec
    for part in schema["$ref"].removeprefix("#/").split("/"):
        target = target[part]
    return target


def _sample(schema: Json, spec: Json, seen: tuple[str, ...] = ()) -> Any:
    """A value for this schema: what it declares, else a placeholder built from its type and limits."""
    ref = schema.get("$ref")
    if ref:
        return None if ref in seen else _sample(_resolve(schema, spec), spec, (*seen, ref))  # a recursive model stops
    if "example" in schema:
        return schema["example"]
    if schema.get("examples"):
        return schema["examples"][0]
    if schema.get("default") is not None:
        return schema["default"]
    if "const" in schema:
        return schema["const"]
    if schema.get("enum"):
        return schema["enum"][0]
    for key in ("anyOf", "oneOf"):
        if key in schema:
            options = [option for option in schema[key] if option.get("type") != "null"]
            return _sample(options[0], spec, seen) if options else None
    if "allOf" in schema:
        parts = [_sample(part, spec, seen) for part in schema["allOf"]]
        if all(isinstance(part, dict) for part in parts):
            return {key: value for part in parts for key, value in part.items()}
        return parts[0]
    if "properties" in schema:
        return {name: _sample(prop, spec, seen) for name, prop in schema["properties"].items()}
    kind = schema.get("type")
    if kind == "object":
        extra = schema.get("additionalProperties")
        return {"key": _sample(extra, spec, seen)} if isinstance(extra, dict) else {}
    if kind == "array":
        item = _sample(schema.get("items", {}), spec, seen)
        return [] if item is None else [item] * schema.get("minItems", 1)
    if kind == "string":
        placeholder = "string".ljust(schema.get("minLength", 0), "x")[: schema.get("maxLength")]
        return _FORMATS.get(schema.get("format", ""), placeholder)
    if kind in ("integer", "number"):
        for limit, step in (("minimum", 0), ("exclusiveMinimum", 1), ("maximum", 0), ("exclusiveMaximum", -1)):
            if limit in schema:
                return schema[limit] + step
        return 1
    return True if kind == "boolean" else None


def _example(holder: Json, spec: Json) -> Any:
    """The example a parameter or media type declares, else a sample of its schema."""
    if "example" in holder:
        return holder["example"]
    for example in holder.get("examples", {}).values():
        if "value" in example:
            return example["value"]
    return _sample(holder.get("schema", {}), spec)


def _text(value: Any) -> str:
    """How a sample looks in a URL, a header or a form."""
    if isinstance(value, list):
        value = value[0] if value else ""
    if value is None:
        return ""
    return value if isinstance(value, str) else json.dumps(value)


def _variable(name: str) -> str:
    return "{{" + name + "}}"


def _field(name: str, value: Any, description: str | None = None, required: bool = True) -> Json:
    """A query parameter, header, path variable or form field. Optional ones start switched off."""
    field: Json = {"key": name, "value": _text(value)}
    if description:
        field["description"] = description
    if not required:
        field["disabled"] = True
    return field


def _is_upload(schema: Json) -> bool:
    if schema.get("format") == "binary" or schema.get("contentMediaType") == "application/octet-stream":
        return True
    return any(_is_upload(option) for option in (*schema.get("anyOf", ()), schema.get("items")) if option)


def _form_fields(holder: Json, spec: Json, multipart: bool) -> list[Json]:
    schema = _resolve(holder.get("schema", {}), spec)
    fields = []
    for name, prop in schema.get("properties", {}).items():
        value = _variable(name) if _SECRET.search(name) else _sample(prop, spec)
        field = _field(name, value, prop.get("description"), name in schema.get("required", []))
        if multipart and _is_upload(prop):
            del field["value"]
            field.update(type="file", src=[])
        elif multipart:
            field["type"] = "text"
        fields.append(field)
    return fields


def _body(media: str, holder: Json, spec: Json) -> Json:
    mode = _FORM_MODES.get(media)
    if mode:
        return {"mode": mode, mode: _form_fields(holder, spec, multipart=mode == "formdata")}
    sample = _example(holder, spec)
    if media.endswith("json"):
        raw, language = json.dumps(sample, indent=2, ensure_ascii=False), "json"
    else:
        raw, language = _text(sample), "text"
    return {"mode": "raw", "raw": raw, "options": {"raw": {"language": language}}}


def _auth_for(scheme: Json) -> Json | None:
    http = scheme.get("scheme", "").lower()
    # OAuth2 and OpenID Connect end in a bearer token too, and logging in fills it (see _token_field).
    if scheme.get("type") in ("oauth2", "openIdConnect") or http == "bearer":
        return _BEARER
    return _BASIC if http == "basic" else None


def _request(path: str, method: str, operation: Json, spec: Json) -> Json:
    fields: dict[str, list[Json]] = {"path": [], "query": [], "header": []}
    auth = None
    for param in operation.get("parameters", []):
        where, name = param["in"], param["name"]
        if where == "header" and name.lower() == "authorization":
            auth = _BEARER  # a dependency reading the header itself
        elif where in fields:  # cookies are left to Postman's cookie jar, which logging in fills
            secret = where != "path" and _SECRET.search(name)
            value = _variable(name) if secret else _example(param, spec)
            fields[where].append(_field(name, value, param.get("description"), param.get("required", False)))

    schemes = spec.get("components", {}).get("securitySchemes", {})
    # An operation's own list wins, and an empty one means public even when the whole API declares security.
    security = operation["security"] if "security" in operation else spec.get("security", [])
    for requirement in security:
        for scheme_name in requirement:
            scheme = schemes.get(scheme_name, {})
            if scheme.get("type") == "apiKey" and scheme["in"] in fields:
                # A plain field, not Postman's API key auth: a request holds one auth, and a key can come with a token.
                fields[scheme["in"]].append(_field(scheme["name"], _variable(scheme["name"])))
            else:
                auth = auth or _auth_for(scheme)

    body = None
    content = operation.get("requestBody", {}).get("content", {})
    if content:
        media, holder = next(iter(content.items()))
        body = _body(media, holder, spec)
        if body["mode"] == "raw":  # Postman sets the Content-Type of a form itself
            fields["header"].insert(0, {"key": "Content-Type", "value": media})

    route = path.replace("{", ":").replace("}", "")
    enabled = [f"{field['key']}={field['value']}" for field in fields["query"] if "disabled" not in field]
    url = {
        "raw": _variable("baseUrl") + route + ("?" + "&".join(enabled) if enabled else ""),
        "host": [_variable("baseUrl")],
        "path": route.split("/")[1:],
        "query": fields["query"],
        "variable": fields["path"],
    }
    return _compact(
        {
            "method": method.upper(),
            "header": fields["header"],
            "url": _compact(url),
            "description": operation.get("description"),
            "auth": auth,
            "body": body,
        }
    )


def _token_field(path: str, method: str, operation: Json, spec: Json) -> str | None:
    """The response field holding a bearer token, when this route is the one that logs you in."""
    if method != "post":
        return None  # a GET reads a token, it doesn't start a session
    for status, response in operation.get("responses", {}).items():
        schema = response.get("content", {}).get("application/json", {}).get("schema", {})
        properties = _resolve(schema, spec).get("properties", {})
        # ponytail: OAuth2's own field names only. A bare `token` could be a reset or invite token; add it if asked.
        for field in ("access_token", "accessToken"):
            if status.startswith("2") and field in properties:
                return field
    route = "/" + path.strip("/")
    for scheme in spec.get("components", {}).get("securitySchemes", {}).values():
        for flow in scheme.get("flows", {}).values():
            token_path = urlsplit(flow.get("tokenUrl", "")).path.strip("/")
            if token_path and route.endswith("/" + token_path):
                return "access_token"
    return None


def _item(path: str, method: str, operation: Json, spec: Json) -> Json:
    item = {
        "name": operation.get("summary") or f"{method.upper()} {path}",
        "request": _request(path, method, operation, spec),
    }
    token_field = _token_field(path, method, operation, spec)
    if token_field:
        script = [
            "// Keeps the token from this response for the requests that need one.",
            "if (pm.response.code < 300) {",
            f"    const token = pm.response.json().{token_field};",
            "    if (token) pm.collectionVariables.set('bearerToken', token);",
            "}",
        ]
        item["event"] = [{"listen": "test", "script": {"type": "text/javascript", "exec": script}}]
    return item


def _specs(app: FastAPI, prefix: str = "") -> Iterator[tuple[str, Json]]:
    """The OpenAPI schema of the app and of each FastAPI app mounted in it, with the path each one is under."""
    yield prefix, app.openapi()
    for route in app.routes:
        if isinstance(route, Mount) and isinstance(route.app, FastAPI) and route.app.openapi_url:
            yield from _specs(route.app, prefix + route.path)


def to_postman(app: FastAPI, *, name: str | None = None, base_url: str | None = None, bearer: bool = False) -> Json:
    """Build a Postman collection (format v2.1) from a FastAPI app.

    Args:
        app: The app. Everything comes from `app.openapi()`, so whatever shows in its docs shows here, including
            parameters and auth declared in `Depends()`, at any depth.
        name: The collection name. Defaults to the app's title.
        base_url: Where the requests go. Defaults to the app's first server, else http://localhost:8000.
        bearer: Send `{{bearerToken}}` on every request that declares no auth of its own. For auth OpenAPI can't see:
            middleware, or a dependency reading `request.headers`.
    """
    specs = list(_specs(app))
    main_spec = specs[0][1]
    servers = main_spec.get("servers", [])
    server = servers[0]["url"] if servers else ""

    requests = []
    for prefix, spec in specs:
        for path, path_item in spec.get("paths", {}).items():
            for method, operation in path_item.items():
                if method in _METHODS:
                    tags = operation.get("tags") or [None]
                    requests.append((tags[0], _item(prefix + path, method, operation, spec)))
    requests.sort(key=lambda request: "event" not in request[1])  # logging in comes first, so a full run has the token

    items: list[Json] = []
    folders: dict[str, Json] = {}
    for tag, item in requests:
        if tag is None:
            items.append(item)
            continue
        if tag not in folders:
            folders[tag] = {"name": tag, "item": []}
            items.append(folders[tag])
        folders[tag]["item"].append(item)

    info = main_spec["info"]
    collection: Json = {
        "info": _compact(
            {
                "name": name or info["title"],
                "description": info.get("description"),
                "version": info.get("version"),
                "schema": "https://schema.getpostman.com/json/collection/v2.1.0/collection.json",
            }
        ),
        "item": items,
    }
    if bearer:
        collection["auth"] = _BEARER
    secrets = re.findall(r"\{\{([\w-]+)\}\}", json.dumps(collection))
    variables = {"baseUrl": (base_url or urljoin("http://localhost:8000", server)).rstrip("/")} | {
        secret: "" for secret in secrets if secret != "baseUrl"
    }
    collection["variable"] = [{"key": key, "value": value} for key, value in variables.items()]
    return collection
