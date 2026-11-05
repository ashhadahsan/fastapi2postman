# fastapi2postman

[![PyPI](https://img.shields.io/pypi/v/fastapi2postman)](https://pypi.org/project/fastapi2postman/)
[![Python](https://img.shields.io/pypi/pyversions/fastapi2postman)](https://pypi.org/project/fastapi2postman/)
[![CI](https://github.com/ashhadahsan/fastapi2postman/actions/workflows/ci.yml/badge.svg)](https://github.com/ashhadahsan/fastapi2postman/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](https://github.com/ashhadahsan/fastapi2postman/blob/main/LICENSE)

**Turn a FastAPI app into a Postman collection you can run straight away.**

```console
$ pip install fastapi2postman
$ fastapi2postman --app main.py
output.json: 25 requests
```

Import `output.json` into Postman, fill in the collection's variables, and send the login request. The token is saved for every other request.

Install it in the same environment as your app, because it imports the app to read its schema. Everything comes from `app.openapi()`, so what shows in your `/docs` shows in the collection.

Two more commands check the app itself: `fastapi2postman routes` lists every route with what protects it, and `fastapi2postman audit` fails CI when a route has no visible auth. See [Check your routes](#check-your-routes).

## What's in the collection

| In your app | In Postman |
| --- | --- |
| `include_router()` and mounted FastAPI apps | Every route with its full path. Routes with `include_in_schema=False` and mounted apps with `openapi_url=None` stay out |
| Tags | A folder per tag |
| A route with several methods | One request per method |
| Path parameters | Path variables such as `:item_id` with a sample value |
| Query and header parameters, including those inside `Depends()` | Filled in, with optional ones switched off |
| Pydantic body models | A sample JSON body that follows your `Field` limits, enums, formats, defaults and declared examples |
| `Form()` and `File()` | Form fields and file pickers |
| Docstrings | Request descriptions |
| Title, version and description | Collection info |
| `servers`, or `--base-url` | A `{{baseUrl}}` variable |

## Auth

Auth is found wherever you declared it: on the route, in a nested `Depends()`, in `Security()`, or in the `dependencies=` of a route, `APIRouter`, `include_router()` or `FastAPI`.

| In your app | In Postman |
| --- | --- |
| `HTTPBearer` and subclasses, any `OAuth2…` scheme, OpenID Connect | Bearer auth with `{{bearerToken}}` |
| A dependency with an `authorization` header parameter | Bearer auth with `{{bearerToken}}` |
| `HTTPBasic` | Basic auth with `{{username}}` and `{{password}}` |
| `APIKeyHeader`, `APIKeyQuery` | The header or query parameter, set to a variable with the same name |
| A query parameter, header or form field whose name contains `token`, `api_key`, `secret` or `password` | The same, so `x_token` is sent as `{{x-token}}` |

Secret variables start blank, so the file holds no credentials. You fill them in inside Postman.

**The token saves itself.** A `POST` route that is your `tokenUrl`, or that returns `access_token` or `accessToken`, gets a script that stores the token in `{{bearerToken}}`. Those requests come first in the collection, so running the whole collection works.

**Auth the schema can't show.** Middleware, or a dependency that reads `request.headers`, doesn't appear in OpenAPI. Use `--bearer` to send `{{bearerToken}}` on every request that has no auth of its own.

## Check your routes

Two more commands read the routes themselves, so they also see what the schema leaves out: routes hidden from the docs, websockets, and plain Starlette routes.

`routes` lists everything the app serves and what protects it, like `flask routes`:

```console
$ fastapi2postman routes --app main.py
METHOD  PATH       AUTH        TAGS    NOTE
GET     /health    -           -
GET     /internal  -           -       hidden from the docs
GET     /me        HTTPBearer  -
POST    /orders    -           orders
*       /static    ?           -       can't read: StaticFiles
```

`audit` fails when a route has no visible auth, so a route merged without its `Depends()` turns CI red:

```console
$ fastapi2postman audit --app main.py --allow "/health" --allow "/static*"
2 of 5 routes have no visible auth:

  GET   /internal  no auth, hidden from the docs
  POST  /orders    no auth

Protect them, or allow the ones meant to be open, for example --allow "/health" or --allow "GET /public/*".
```

It exits with 1 when it finds any, and 0 otherwise. `--allow` takes a path or a method and a path, and `*` matches anything, including `/`. An `--allow` that matches no route prints a warning, because it could let a route added later through unnoticed.

Auth counts when a route's dependencies declare it, at any depth: a security scheme such as `HTTPBearer`, or a required header, query parameter or cookie named like a credential, such as `x_token` or `session_id`.

**`audit` reads what routes declare and doesn't run them.** So:

- Auth in middleware, or in a dependency reading `request.headers`, looks like no auth. Allow those routes.
- A dependency that declares a token but never checks it still counts as auth. So does `auto_error=False`, which `routes` shows as `HTTPBearer (optional)`.
- Plain Starlette routes and mounted apps such as `StaticFiles` have nothing to read, so they're always flagged until you allow them.

## Pointing it at your app

Run it from your project root.

| `--app` | Loads |
| --- | --- |
| `main.py` | `app` from that file |
| `main.py:api` | `api` from that file |
| `src/shop/main.py` | `app` from that file. Relative imports work if the folder has an `__init__.py` |
| `shop.main` | `app` from that module |
| `shop.main:api` | `api` from that module |
| `shop.main:create_app` | The app that this factory function returns |

## Options

```text
--app APP            the app: main.py, main.py:api or package.main:api. The
                     name defaults to app, and may be a factory
--output OUTPUT      output file (default: output.json)
--name NAME          collection name (default: the app's title)
--base-url BASE_URL  where the requests go (default: the app's first server,
                     else http://localhost:8000)
--host HOST          shorthand for --base-url http://HOST:PORT
--port PORT          shorthand for --base-url http://HOST:PORT
--bearer             send {{bearerToken}} on every request without auth of
                     its own: for auth in middleware, or in a dependency
                     reading request.headers, which the app's schema can't
                     show
--version            show program's version number and exit
```

## From Python

```python
from fastapi2postman import to_postman

collection = to_postman(app, name="Shop", base_url="https://api.example.com")
```

`to_postman` returns the collection as a dict.

## Limits

- **Samples are placeholders.** Any `pattern`, and validators that compare fields, can't be read from the schema. Declare `examples=` on the field where a sample gets rejected.
- **A request holds one auth.** If a route declares several, the first one Postman supports is used. API keys don't count, because they're sent as plain headers or query parameters.
- **Cookies are left to Postman's cookie jar**, which fills up when you log in. That covers `Cookie()` parameters and `APIKeyCookie`.
- **The token script reads the top level of a JSON response.** A login returning a bare `token` field or a nested token isn't detected, because a bare `token` could just as well be a reset or invite token.
- **Only FastAPI apps are followed into mounts.** Other mounted apps have no schema to read.

## Contributing

See [CONTRIBUTING.md](https://github.com/ashhadahsan/fastapi2postman/blob/main/CONTRIBUTING.md). Each change is checked by running a generated collection in Newman, Postman's command-line runner, against a live app.

## License

MIT. Inspired by [flask2postman](https://github.com/numberly/flask2postman).
