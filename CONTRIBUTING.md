# Contributing

## Setup

```console
$ uv sync
```

That installs the package and the test tools. You need [uv](https://docs.astral.sh/uv/).

## Before you open a pull request

```console
$ uv run ruff check && uv run ruff format --check
$ uv run mypy
$ uv run coverage run -m pytest && uv run coverage report --fail-under=95
$ ./tests/newman.sh
```

`tests/newman.sh` runs a generated collection in Newman, Postman's command-line runner, against `tests/sample_app.py`, and every request must get a 2xx. It needs Node and `jq`, and port 8000 free. When you add support for something, add a route for it to the sample app that fails unless the generated request is right.

- **Commits.** Use [Conventional Commits](https://www.conventionalcommits.org/): `feat:`, `fix:`, `docs:`, `test:`, `ci:`, `chore:`. Keep pull requests small.
- **Changelog.** Add user-visible changes to `CHANGELOG.md` under `[Unreleased]`.
- **Dependencies.** FastAPI stays the only runtime dependency. Read everything from `app.openapi()`, not from FastAPI's routing internals: walking `app.routes` is what lost router routes when FastAPI 0.137 changed them.
