# Changelog

All notable changes are documented here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses [Semantic Versioning](https://semver.org/).

## [Unreleased]

## [0.3.0] - 2026-11-05

### Added

- `fastapi2postman routes` lists every route the app serves with what protects it, like `flask routes`. It also shows routes hidden from the docs, websockets and plain Starlette routes.
- `fastapi2postman audit` fails when a route has no visible auth, so a route merged without its `Depends()` turns CI red. Routes meant to be open are allowed with `--allow`.

## [0.2.0] - 2026-11-05

### Added

- Sample values for path, query and header parameters, and sample bodies for JSON, form and file-upload requests. They follow your `Field` limits, enums, formats, defaults and declared examples. Optional parameters start switched off.
- Auth, wherever you declare it: on a route, in a nested `Depends()`, in `Security()`, or in the `dependencies=` of a route, `APIRouter`, `include_router()` or `FastAPI`. Bearer, OAuth2 and OpenID Connect use `{{bearerToken}}`, basic auth uses `{{username}}` and `{{password}}`, and API keys are sent from a variable named after them.
- Secrets stay out of the file. Query parameters, headers and form fields named like a token, API key, secret or password are sent from a blank variable.
- Login requests save their token. A `POST` route that is your `tokenUrl`, or that returns `access_token` or `accessToken`, stores the token in `{{bearerToken}}` and comes first in the collection.
- `--bearer`, for auth OpenAPI can't show: middleware, or a dependency reading `request.headers`.
- A folder per tag, and docstrings as request descriptions.
- FastAPI apps mounted with `app.mount()`, unless they hide their docs with `openapi_url=None`.
- A `{{baseUrl}}` variable, set from the new `--base-url`, from `--host` and `--port`, or from the app's first `servers` entry. HTTPS base URLs now work.
- `--app` accepts `module:attribute` (thanks to Yash Savalia), `file.py:attribute`, a file inside a package, and a factory function. Clear errors when the app can't be found.
- `--version`, a line reporting how many requests were written, and `to_postman()` for use from Python.

### Fixed

- Routes from `include_router()` were silently left out on FastAPI 0.137.0 and later, because those versions no longer list them in `app.routes`. The collection is now built from `app.openapi()`.
- A route with several methods produced one request with an invalid method such as `GET,POST`. It now produces one request per method.
- Path parameters were sent as literal text such as `{item_id}`. They are now Postman path variables, and converters such as `{name:path}` no longer leak into the URL.
- `--app module:attribute` couldn't find modules in the current directory when run as a console script.

### Changed

- **Breaking:** requires Python 3.11 and FastAPI 0.105 or later.
- **Breaking:** request names come from the route's summary, so `create_item` becomes `Create Item`. The default collection name is the app's title, not `FastAPI API`.
- **Breaking:** routes with `include_in_schema=False` are left out, matching your `/docs`.

### Removed

- **Breaking:** `register_routes()`. Use `to_postman()`.
- The unused `click`, `requests` and `uvicorn` dependencies. FastAPI is now the only one.

## [0.1.2] - 2023-05-11

The last release before this changelog started.

[Unreleased]: https://github.com/ashhadahsan/fastapi2postman/compare/v0.3.0...HEAD
[0.3.0]: https://github.com/ashhadahsan/fastapi2postman/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/ashhadahsan/fastapi2postman/releases/tag/v0.2.0
[0.1.2]: https://pypi.org/project/fastapi2postman/0.1.2/
