#!/usr/bin/env bash
# Runs a generated collection in Newman, Postman's own runner, against the live sample app. Every request must get a
# 2xx, which only happens if Postman reads the collection as meant: the path variables, the sample bodies, the login
# saving its token for the secured routes, and the secrets coming from variables. Run from the root of the repo.
set -euo pipefail

SECRET=kept-in-a-postman-variable
out=$(mktemp -d)

uv run fastapi2postman --app tests/sample_app.py --base-url http://127.0.0.1:8000 --output "$out/collection.json"

uv run uvicorn --app-dir tests sample_app:app --port 8000 --log-level warning &
server=$!
trap 'kill "$server"' EXIT
for _ in $(seq 30); do
  curl -sf http://127.0.0.1:8000/openapi.json >/dev/null && break
  sleep 1
done

# bearerToken is left out on purpose: the login route has to fill it.
npx --yes newman@6.2.3 run "$out/collection.json" \
  --env-var "username=$SECRET" \
  --env-var "password=$SECRET" \
  --env-var "X-API-Key=$SECRET" \
  --env-var "api_key=$SECRET" \
  --env-var "x-token=$SECRET" \
  --env-var "token=$SECRET" \
  --reporters cli,json --reporter-json-export "$out/run.json"

# Newman only fails on its own errors and on failed test scripts, so check the status codes here.
jq -e '(.run.executions | length) > 0 and all(.run.executions[]; .response.code < 300)' "$out/run.json"
