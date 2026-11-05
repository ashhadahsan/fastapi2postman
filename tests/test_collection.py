"""What the collection for tests/sample_app.py, and for hand-written OpenAPI schemas, must hold."""

import json
from pathlib import Path
from typing import Annotated, Any

import jsonschema
import pytest
from fastapi import APIRouter, Cookie, Depends, FastAPI
from fastapi.security import APIKeyHeader, OAuth2PasswordBearer
from pydantic import BaseModel
from sample_app import Item, app, current_user

from fastapi2postman import to_postman

COLLECTION = to_postman(app)


def flat(collection: dict[str, Any]) -> list[dict[str, Any]]:
    return [leaf for entry in collection["item"] for leaf in entry.get("item", [entry])]


def leaf(name: str, collection: dict[str, Any] = COLLECTION) -> dict[str, Any]:
    return next(entry for entry in flat(collection) if entry["name"] == name)


def request(name: str, collection: dict[str, Any] = COLLECTION) -> dict[str, Any]:
    return leaf(name, collection)["request"]


def from_schema(operation: dict[str, Any], **top: Any) -> dict[str, Any]:
    """The collection for a one-route app whose OpenAPI schema is written by hand."""
    custom = FastAPI()
    custom.openapi = lambda: {"info": {"title": "T", "version": "1"}, "paths": {"/x": {"post": operation}}, **top}
    return to_postman(custom)


def sample(schema: dict[str, Any], **components: Any) -> Any:
    """The JSON body written for a request body with this schema."""
    content = {"application/json": {"schema": schema}}
    collection = from_schema({"requestBody": {"content": content}}, components={"schemas": components})
    return json.loads(collection["item"][0]["request"]["body"]["raw"])


def test_matches_the_official_postman_schema():
    schema = json.loads((Path(__file__).parent / "postman-collection-v2.1.schema.json").read_text())
    jsonschema.validate(COLLECTION, schema)


def test_keeps_routes_from_included_routers():
    # FastAPI no longer flattens include_router() into app.routes: walking that list loses all of these.
    router = APIRouter()
    router.get("/included")(lambda: None)
    routed = FastAPI()
    routed.include_router(router)
    assert [entry["request"]["url"]["path"] for entry in flat(to_postman(routed))] == [["included"]]


def test_leaves_out_routes_hidden_from_the_docs():
    assert not [entry for entry in flat(COLLECTION) if "hidden" in entry["request"]["url"]["path"]]


def test_a_route_with_several_methods_becomes_one_request_per_method():
    methods = [entry["request"]["method"] for entry in flat(COLLECTION) if entry["name"] == "Ping"]
    assert sorted(methods) == ["GET", "POST"]


def test_groups_requests_into_a_folder_per_tag():
    folders = {entry["name"]: entry["item"] for entry in COLLECTION["item"] if "item" in entry}
    assert list(folders) == ["auth", "items", "forms", "secured", "reports", "audit", "admin"]
    assert [entry["name"] for entry in folders["items"]] == [
        "Create Item",
        "Read Item",
        "Read File",
        "Example declared on the body",
    ]


def test_untagged_requests_stay_at_the_top_level():
    assert [entry["name"] for entry in COLLECTION["item"] if "item" not in entry] == ["Ping", "Ping"]


def test_docstring_becomes_the_description():
    assert request("Create Item")["description"] == "Add an item to the catalogue."
    assert "description" not in request("Read Item")


def test_path_parameters_become_postman_path_variables():
    url = request("Read Item")["url"]
    assert url["host"] == ["{{baseUrl}}"]
    assert url["path"] == ["items", ":item_id"]
    assert url["variable"] == [{"key": "item_id", "value": "1"}]


def test_path_converters_are_dropped_from_the_variable_name():
    assert request("Read File")["url"]["path"] == ["items", ":item_id", "files", ":name"]


def test_a_trailing_slash_is_kept():
    # FastAPI answers /items with a redirect when the route is /items/.
    url = request("Create Item")["url"]
    assert url["path"] == ["items", ""]
    assert url["raw"] == "{{baseUrl}}/items/"


def test_required_query_parameters_are_on_and_optional_ones_off():
    url = request("Read Item")["url"]
    query = {entry["key"]: entry for entry in url["query"]}
    assert query["color"] == {"key": "color", "value": "red"}
    assert query["limit"] == {"key": "limit", "value": "10", "description": "Page size", "disabled": True}
    assert query["verbose"]["value"] == "false"
    assert query["q"]["value"] == "string"
    assert query["labels"]["value"] == "string"
    assert url["raw"] == "{{baseUrl}}/items/:item_id?color=red"


def test_header_parameters():
    assert request("Read Item")["header"] == [
        {"key": "x-request-id", "value": "string", "description": "Trace id"},
        {"key": "x-debug", "value": "string", "disabled": True},
    ]


def test_cookie_parameters_are_left_to_the_cookie_jar():
    cookies = FastAPI()

    @cookies.get("/x")
    def read(session: Annotated[str, Cookie()]) -> None: ...

    assert "header" not in request("Read", to_postman(cookies))


def test_json_body_sample_is_accepted_by_the_model():
    created = request("Create Item")
    assert created["method"] == "POST"
    assert created["header"] == [{"key": "Content-Type", "value": "application/json"}]
    assert created["body"]["options"] == {"raw": {"language": "json"}}
    body = json.loads(created["body"]["raw"])
    Item.model_validate(body)
    assert body["name"] == "stringxxxx"  # min_length
    assert body["color"] == "red"  # enum
    assert body["size"] == {"width": 1, "height": 5}  # gt, ge, nested model
    assert body["contact"] == "user@example.com"  # format
    assert body["tags"] == ["string"]
    assert body["stock"] == {"key": 1}
    assert body["quantity"] == 7  # default
    assert body["motto"] == "Fresh every day"  # examples
    assert body["note"] == "string"  # a default of None shows the type instead
    assert body["parent"] is None  # recursive model


def test_examples_declared_on_the_body_and_on_a_parameter_win():
    declared = request("Example declared on the body")
    assert json.loads(declared["body"]["raw"]) == {"from": "openapi_examples"}
    assert declared["url"]["query"][0]["value"] == "-created"


def test_a_single_declared_example_wins_too():
    content = {"application/json": {"schema": {"type": "string"}, "example": "declared"}}
    collection = from_schema(
        {
            "requestBody": {"content": content},
            "parameters": [{"name": "p", "in": "query", "schema": {"type": "string"}, "example": "too"}],
        }
    )
    sent = collection["item"][0]["request"]
    assert json.loads(sent["body"]["raw"]) == "declared"
    assert sent["url"]["query"][0]["value"] == "too"


def test_urlencoded_form_body():
    assert request("Contact")["body"] == {
        "mode": "urlencoded",
        "urlencoded": [
            {"key": "subject", "value": "string", "description": "What it's about"},
            {"key": "urgent", "value": "false", "disabled": True},
        ],
    }
    assert "header" not in request("Contact")  # Postman sets the Content-Type of a form


def test_multipart_body_with_file_fields():
    assert request("Upload")["body"] == {
        "mode": "formdata",
        "formdata": [
            {"key": "title", "value": "string", "type": "text"},
            {"key": "attachment", "type": "file", "src": [], "disabled": True},
            {"key": "extras", "type": "file", "src": [], "disabled": True},
        ],
    }


def test_older_fastapi_file_schema_is_a_file_field_too():
    schema = {"properties": {"f": {"type": "string", "format": "binary"}}, "required": ["f"]}
    collection = from_schema({"requestBody": {"content": {"multipart/form-data": {"schema": schema}}}})
    assert collection["item"][0]["request"]["body"]["formdata"] == [{"key": "f", "type": "file", "src": []}]


@pytest.mark.parametrize(
    ("media", "schema", "raw", "language"),
    [
        ("text/plain", {"type": "string"}, "string", "text"),
        ("application/vnd.api+json", {"type": "string"}, '"string"', "json"),
    ],
)
def test_other_body_types_are_sent_raw(media: str, schema: dict[str, Any], raw: str, language: str):
    sent = from_schema({"requestBody": {"content": {media: {"schema": schema}}}})["item"][0]["request"]
    assert sent["header"] == [{"key": "Content-Type", "value": media}]
    assert sent["body"] == {"mode": "raw", "raw": raw, "options": {"raw": {"language": language}}}


@pytest.mark.parametrize(
    ("schema", "expected"),
    [
        ({}, None),
        ({"type": "null"}, None),
        ({"type": "boolean"}, True),
        ({"type": "number"}, 1),
        ({"type": "integer", "minimum": 5}, 5),
        ({"type": "integer", "exclusiveMinimum": 5}, 6),
        ({"type": "integer", "maximum": -3}, -3),
        ({"type": "integer", "exclusiveMaximum": 0}, -1),
        ({"type": "string", "minLength": 8}, "stringxx"),
        ({"type": "string", "maxLength": 3}, "str"),
        ({"type": "string", "format": "uuid"}, "00000000-0000-4000-8000-000000000000"),
        ({"type": "string", "format": "date-time"}, "2026-01-01T00:00:00Z"),
        ({"type": "string", "format": "password"}, "string"),
        ({"const": "only"}, "only"),
        ({"enum": ["first", "second"]}, "first"),
        ({"type": "string", "example": "a", "default": "b"}, "a"),
        ({"type": "string", "examples": ["a"], "default": "b"}, "a"),
        ({"type": "string", "default": "b"}, "b"),
        ({"type": "string", "default": None}, "string"),
        ({"oneOf": [{"type": "integer"}, {"type": "string"}]}, 1),
        ({"anyOf": [{"type": "null"}, {"type": "boolean"}]}, True),
        ({"anyOf": [{"type": "null"}]}, None),
        ({"type": "array"}, []),
        ({"type": "array", "items": {"type": "integer"}, "minItems": 2}, [1, 1]),
        ({"type": "object"}, {}),
        ({"type": "object", "additionalProperties": True}, {}),
        ({"type": "object", "additionalProperties": {"type": "integer"}}, {"key": 1}),
        ({"properties": {"a": {"type": "integer"}}}, {"a": 1}),
        (
            {"allOf": [{"properties": {"a": {"type": "integer"}}}, {"properties": {"b": {"type": "boolean"}}}]},
            {"a": 1, "b": True},
        ),
        ({"allOf": [{"$ref": "#/components/schemas/Pick"}]}, "one"),
    ],
)
def test_sample_values(schema: dict[str, Any], expected: Any):
    assert sample(schema, Pick={"enum": ["one", "two"]}) == expected


def test_a_recursive_list_ends_empty():
    node = {"properties": {"children": {"type": "array", "items": {"$ref": "#/components/schemas/Node"}}}}
    assert sample({"$ref": "#/components/schemas/Node"}, Node=node) == {"children": []}


BEARER = {"type": "bearer", "bearer": [{"key": "token", "value": "{{bearerToken}}", "type": "string"}]}


@pytest.mark.parametrize(
    "name",
    [
        "With Bearer",
        "With Jwt",  # a subclass of HTTPBearer
        "With Current User",  # Depends(current_user), which depends on the OAuth2 scheme
        "With Nested Dependency",  # one level further down
        "With Scopes",  # Security(oauth2, scopes=[...])
        "List Reports",  # APIRouter(dependencies=[...])
        "Read Audit",  # include_router(router, dependencies=[...])
    ],
)
def test_bearer_token_is_found_through_depends(name: str):
    assert request(name)["auth"] == BEARER


def test_bearer_token_from_dependencies_on_the_whole_app():
    guarded = FastAPI(dependencies=[Depends(current_user)])
    guarded.get("/x")(lambda: None)
    assert flat(to_postman(guarded))[0]["request"]["auth"] == BEARER


def test_a_dependency_reading_the_authorization_header_itself_means_a_bearer_token():
    sent = request("With Authorization Header")
    assert sent["auth"] == BEARER
    assert "header" not in sent  # not a literal "Authorization: string" as well


def test_a_public_route_has_no_auth():
    assert "auth" not in request("Ping")


def test_basic_auth():
    assert request("With Basic")["auth"] == {
        "type": "basic",
        "basic": [
            {"key": "username", "value": "{{username}}", "type": "string"},
            {"key": "password", "value": "{{password}}", "type": "string"},
        ],
    }


def test_api_keys_are_sent_from_a_variable():
    assert request("With Header Key")["header"] == [{"key": "X-API-Key", "value": "{{X-API-Key}}"}]
    assert request("With Query Key")["url"]["query"] == [{"key": "api_key", "value": "{{api_key}}"}]
    assert request("With Query Key")["url"]["raw"] == "{{baseUrl}}/secured/query-key?api_key={{api_key}}"


def test_an_api_key_and_a_bearer_token_on_one_route():
    sent = request("With Bearer And Key")
    assert sent["auth"] == BEARER
    assert sent["header"] == [{"key": "X-API-Key", "value": "{{X-API-Key}}"}]


def test_secret_looking_parameters_inside_a_dependency_are_sent_from_a_variable():
    assert request("With Custom Header")["header"] == [{"key": "x-token", "value": "{{x-token}}"}]
    assert request("With Query Token")["url"]["query"] == [{"key": "token", "value": "{{token}}"}]


def test_a_password_in_a_form_is_sent_from_a_variable():
    fields = {field["key"]: field for field in request("Issue Token")["body"]["urlencoded"]}
    assert fields["password"]["value"] == "{{password}}"
    assert fields["client_secret"]["value"] == "{{client_secret}}"
    assert fields["username"]["value"] == "string"


def test_a_path_parameter_is_never_taken_for_a_secret():
    tokens = FastAPI()

    @tokens.get("/tokens/{token_id}")
    def read(token_id: str) -> None: ...

    assert flat(to_postman(tokens))[0]["request"]["url"]["variable"][0]["value"] == "string"


def test_parameters_inside_a_dependency_are_included():
    query = request("List Reports")["url"]["query"]
    assert [(entry["key"], entry["value"]) for entry in query] == [("skip", "0"), ("limit", "20")]


def script(name: str, collection: dict[str, Any] = COLLECTION) -> str:
    events = leaf(name, collection)["event"]
    assert [event["listen"] for event in events] == ["test"]
    assert events[0]["script"]["type"] == "text/javascript"
    return "\n".join(events[0]["script"]["exec"])


def test_the_route_named_as_tokenurl_saves_the_token():
    assert "pm.response.json().access_token" in script("Issue Token")
    assert "pm.collectionVariables.set('bearerToken', token)" in script("Issue Token")


def test_a_response_without_the_token_leaves_the_saved_one_alone():
    assert "if (token) pm.collectionVariables.set" in script("Issue Token")


def test_a_route_returning_an_access_token_saves_it():
    assert "pm.response.json().access_token" in script("Log In")


def test_a_camelcase_access_token_is_saved_too():
    responses = {
        "200": {
            "content": {
                "application/json": {"schema": {"$ref": "#/components/schemas/T"}},
            }
        }
    }
    schemas = {"T": {"properties": {"accessToken": {"type": "string"}}}}
    collection = from_schema({"responses": responses, "summary": "S"}, components={"schemas": schemas})
    assert "pm.response.json().accessToken" in script("S", collection)


def test_other_routes_save_nothing():
    assert "event" not in leaf("Create Item")
    assert "event" not in leaf("With Current User")


def test_only_a_post_can_log_you_in():
    # A GET returning a token reads an existing one; it must not replace the token in use.
    class Out(BaseModel):
        access_token: str

    readers = FastAPI()

    @readers.get("/me/token")
    def read_token() -> Out: ...

    assert "event" not in flat(to_postman(readers))[0]


def test_an_error_response_is_not_where_a_token_comes_from():
    responses = {"400": {"content": {"application/json": {"schema": {"properties": {"access_token": {}}}}}}}
    assert "event" not in from_schema({"responses": responses})["item"][0]


def test_tokenurl_given_as_a_full_url():
    flows = {"password": {"tokenUrl": "https://example.com/x", "scopes": {}}}
    schemes = {"oauth": {"type": "oauth2", "flows": flows}}
    assert "event" in from_schema({}, components={"securitySchemes": schemes})["item"][0]


def test_tokenurl_in_a_mounted_app():
    sub = FastAPI()
    sub.post("/token")(lambda: None)
    sub.get("/me", dependencies=[Depends(OAuth2PasswordBearer(tokenUrl="token"))])(lambda: None)
    outer = FastAPI()
    outer.mount("/v2", sub)
    logs_in = {tuple(entry["request"]["url"]["path"]): "event" in entry for entry in flat(to_postman(outer))}
    assert logs_in == {("v2", "token"): True, ("v2", "me"): False}


def test_tokenurl_matches_whole_path_segments():
    # /api-token is not the route named "token".
    apps = FastAPI()
    apps.post("/api-token")(lambda: None)
    apps.get("/me", dependencies=[Depends(OAuth2PasswordBearer(tokenUrl="token"))])(lambda: None)
    assert not [entry for entry in flat(to_postman(apps)) if "event" in entry]


def test_the_login_runs_first_so_a_full_run_has_the_token():
    assert COLLECTION["item"][0]["name"] == "auth"
    assert [entry["name"] for entry in COLLECTION["item"][0]["item"]] == ["Issue Token", "Log In"]
    untagged = FastAPI()
    untagged.get("/a")(lambda: None)
    login = OAuth2PasswordBearer(tokenUrl="login")
    untagged.get("/b", dependencies=[Depends(login)])(lambda: None)
    untagged.post("/login")(lambda: None)
    assert [entry["request"]["url"]["path"] for entry in to_postman(untagged)["item"]] == [["login"], ["a"], ["b"]]


def test_bearer_option_covers_auth_openapi_cannot_see():
    # Middleware, or a dependency reading request.headers.
    plain = FastAPI()
    plain.get("/x")(lambda: None)
    assert "auth" not in to_postman(plain)
    collection = to_postman(plain, bearer=True)
    assert collection["auth"] == BEARER
    assert {"key": "bearerToken", "value": ""} in collection["variable"]
    assert "auth" not in collection["item"][0]["request"]  # it inherits


def test_bearer_option_leaves_routes_with_their_own_auth_alone():
    collection = to_postman(app, bearer=True)
    assert request("With Basic", collection)["auth"]["type"] == "basic"


def test_routes_in_a_mounted_app_get_its_prefix_and_its_security():
    stats = request("Stats")
    assert stats["url"]["path"] == ["admin", "stats"]
    assert stats["header"] == [{"key": "X-API-Key", "value": "{{X-API-Key}}"}]


def test_a_mounted_app_hidden_from_the_docs_stays_out():
    # openapi_url=None says this app has no public schema, so it mustn't land in a collection people share.
    internal = FastAPI(openapi_url=None)
    internal.get("/secret-route")(lambda: None)
    outer = FastAPI()
    outer.mount("/internal", internal)
    assert flat(to_postman(outer)) == []


def test_an_api_key_declared_twice_is_sent_once():
    key = APIKeyHeader(name="X-API-Key")
    router = APIRouter(dependencies=[Depends(key)])
    router.get("/x", dependencies=[Depends(key)])(lambda: None)
    twice = FastAPI(dependencies=[Depends(key)])
    twice.include_router(router)
    assert flat(to_postman(twice))[0]["request"]["header"] == [{"key": "X-API-Key", "value": "{{X-API-Key}}"}]


SCHEMES = {
    "cookie": {"type": "apiKey", "in": "cookie", "name": "sid"},
    "digest": {"type": "http", "scheme": "digest"},
    "oidc": {"type": "openIdConnect", "openIdConnectUrl": "https://example.com"},
    "shouting": {"type": "http", "scheme": "Bearer"},
    "basic": {"type": "http", "scheme": "basic"},
}


@pytest.mark.parametrize(
    ("security", "expected"),
    [
        ([{"cookie": []}], None),  # left to the cookie jar, like cookie parameters
        ([{"digest": []}], None),
        ([{"missing": []}], None),
        ([{}], None),  # anonymous allowed
        ([{"oidc": []}], BEARER),
        ([{"shouting": []}], BEARER),
        ([{"cookie": []}, {"shouting": []}], BEARER),  # the first one Postman can do
        ([{"shouting": []}, {"basic": []}], BEARER),  # a request holds one auth
    ],
)
def test_auth_edge_cases(security: list[dict[str, Any]], expected: Any):
    sent = from_schema({"security": security}, components={"securitySchemes": SCHEMES})["item"][0]["request"]
    assert sent.get("auth") == expected


def test_security_declared_for_the_whole_api_applies_to_each_request():
    collection = from_schema({}, security=[{"shouting": []}], components={"securitySchemes": SCHEMES})
    assert collection["item"][0]["request"]["auth"] == BEARER


def test_a_route_can_opt_out_of_security_declared_for_the_whole_api():
    collection = from_schema({"security": []}, security=[{"shouting": []}], components={"securitySchemes": SCHEMES})
    assert "auth" not in collection["item"][0]["request"]


def test_a_parameter_without_a_type_is_left_blank():
    untyped = FastAPI()

    @untyped.get("/x/{anything}")
    def read(anything): ...

    assert flat(to_postman(untyped))[0]["request"]["url"]["variable"] == [{"key": "anything", "value": ""}]


def test_collection_variables_hold_the_base_url_and_blank_secrets():
    variables = {variable["key"]: variable["value"] for variable in COLLECTION["variable"]}
    assert COLLECTION["variable"][0] == {"key": "baseUrl", "value": "http://localhost:8000"}
    del variables["baseUrl"]
    assert set(variables) == {
        "bearerToken",
        "username",
        "password",
        "client_secret",
        "X-API-Key",
        "api_key",
        "x-token",
        "token",
    }
    assert set(variables.values()) == {""}


def test_no_secret_variables_without_auth():
    assert [variable["key"] for variable in from_schema({})["variable"]] == ["baseUrl"]


@pytest.mark.parametrize(
    ("servers", "base_url", "expected"),
    [
        (None, None, "http://localhost:8000"),
        (None, "https://api.example.com/", "https://api.example.com"),
        ([{"url": "https://prod.example.com/v1/"}], None, "https://prod.example.com/v1"),
        ([{"url": "/api"}], None, "http://localhost:8000/api"),
        ([{"url": "https://prod.example.com"}], "http://other", "http://other"),
    ],
)
def test_base_url(servers: list[dict[str, str]] | None, base_url: str | None, expected: str):
    collection = to_postman(FastAPI(servers=servers), base_url=base_url)
    assert collection["variable"][0] == {"key": "baseUrl", "value": expected}


def test_info_comes_from_the_app():
    assert COLLECTION["info"] == {
        "name": "Shop",
        "description": "A small shop.",
        "version": "2.1.0",
        "schema": "https://schema.getpostman.com/json/collection/v2.1.0/collection.json",
    }


def test_name_can_be_overridden():
    assert to_postman(app, name="Mine")["info"]["name"] == "Mine"


def test_other_keys_on_a_path_are_not_taken_for_methods():
    custom = FastAPI()
    custom.openapi = lambda: {
        "info": {"title": "T", "version": "1"},
        "paths": {"/x": {"parameters": [{"name": "p", "in": "query"}], "summary": "not a method", "get": {}}},
    }
    assert [entry["request"]["method"] for entry in flat(to_postman(custom))] == ["GET"]


def test_an_operation_without_a_summary_is_named_after_its_route():
    assert from_schema({})["item"][0]["name"] == "POST /x"
