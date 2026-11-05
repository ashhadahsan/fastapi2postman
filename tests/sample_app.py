"""The app the tests convert and tests/newman.sh runs: a route answers 2xx only if the generated request is valid."""

from datetime import date, datetime
from enum import StrEnum
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Body, Depends, FastAPI, File, Form, Header, HTTPException, Query, Security, UploadFile
from fastapi.security import (
    APIKeyHeader,
    APIKeyQuery,
    HTTPAuthorizationCredentials,
    HTTPBasic,
    HTTPBasicCredentials,
    HTTPBearer,
    OAuth2PasswordBearer,
    OAuth2PasswordRequestForm,
)
from pydantic import BaseModel, Field

ISSUED_TOKEN = "issued-by-the-login-route"
SECRET = "kept-in-a-postman-variable"  # tests/newman.sh sets the variables to this


class Color(StrEnum):
    red = "red"
    blue = "blue"


class Size(BaseModel):
    width: int = Field(gt=0)
    height: int = Field(ge=5)


class Item(BaseModel):
    name: str = Field(min_length=10)
    sku: UUID
    color: Color
    price: float = Field(gt=0)
    created: datetime
    released: date
    contact: str = Field(json_schema_extra={"format": "email"})
    size: Size
    tags: list[str]
    stock: dict[str, int]
    note: str | None = None
    quantity: int = 7
    motto: str = Field(examples=["Fresh every day"])
    parent: "Item | None" = None


def check(value: str | None, expected: str = SECRET) -> None:
    if value != expected:
        raise HTTPException(401, f"got {value!r}")


# Logging in. Declared last on purpose: the collection must still run these first.
auth = APIRouter(prefix="/auth", tags=["auth"])


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"


@auth.post("/token")
def issue_token(form: Annotated[OAuth2PasswordRequestForm, Depends()]) -> dict[str, str]:
    """No response model: only OAuth2PasswordBearer's tokenUrl gives this route away."""
    check(form.password)
    return {"access_token": ISSUED_TOKEN, "token_type": "bearer"}


@auth.post("/login")
def log_in(email: Annotated[str, Body(embed=True)]) -> Token:
    """The response model gives this one away."""
    return Token(access_token=ISSUED_TOKEN)


# Auth through Depends(), the ways real apps write it.
oauth2 = OAuth2PasswordBearer(tokenUrl="auth/token")


def current_user(token: Annotated[str, Depends(oauth2)]) -> str:
    check(token, ISSUED_TOKEN)
    return "me"


def current_admin(user: Annotated[str, Depends(current_user)]) -> str:
    return user


class JWTBearer(HTTPBearer):
    """How people usually write a JWT check."""


def token_in_authorization_header(authorization: Annotated[str, Header()]) -> None:
    check(authorization, f"Bearer {ISSUED_TOKEN}")


def token_in_custom_header(x_token: Annotated[str, Header()]) -> None:
    check(x_token)


def token_in_query(token: str) -> None:
    check(token)


class Page:
    def __init__(self, skip: int = 0, limit: int = 20) -> None:
        self.skip = skip
        self.limit = limit


secured = APIRouter(prefix="/secured", tags=["secured"])
_HEADER_KEY = APIKeyHeader(name="X-API-Key")
_QUERY_KEY = APIKeyQuery(name="api_key")


@secured.get("/bearer")
def with_bearer(credentials: Annotated[HTTPAuthorizationCredentials, Depends(HTTPBearer())]) -> None:
    check(credentials.credentials, ISSUED_TOKEN)


@secured.get("/jwt")
def with_jwt(credentials: Annotated[HTTPAuthorizationCredentials, Depends(JWTBearer())]) -> None:
    check(credentials.credentials, ISSUED_TOKEN)


@secured.get("/user")
def with_current_user(user: Annotated[str, Depends(current_user)]) -> str:
    return user


@secured.get("/admin")
def with_nested_dependency(user: Annotated[str, Depends(current_admin)]) -> str:
    return user


@secured.get("/scoped")
def with_scopes(token: Annotated[str, Security(oauth2, scopes=["read"])]) -> None:
    check(token, ISSUED_TOKEN)


@secured.get("/basic")
def with_basic(credentials: Annotated[HTTPBasicCredentials, Depends(HTTPBasic())]) -> None:
    check(credentials.username)
    check(credentials.password)


@secured.get("/header-key")
def with_header_key(key: Annotated[str, Depends(_HEADER_KEY)]) -> None:
    check(key)


@secured.get("/query-key")
def with_query_key(key: Annotated[str, Depends(_QUERY_KEY)]) -> None:
    check(key)


@secured.get("/both", dependencies=[Depends(current_user), Depends(_HEADER_KEY)])
def with_bearer_and_key() -> None: ...


@secured.get("/authorization-header", dependencies=[Depends(token_in_authorization_header)])
def with_authorization_header() -> None: ...


@secured.get("/custom-header", dependencies=[Depends(token_in_custom_header)])
def with_custom_header() -> None: ...


@secured.get("/query-token", dependencies=[Depends(token_in_query)])
def with_query_token() -> None: ...


reports = APIRouter(prefix="/reports", tags=["reports"], dependencies=[Depends(current_user)])


@reports.get("")
def list_reports(page: Annotated[Page, Depends()]) -> int:
    """Auth comes from the router; skip and limit from a class used as a dependency."""
    return page.limit


audit = APIRouter(prefix="/audit", tags=["audit"])


@audit.get("")
def read_audit() -> None:
    """Auth comes from the include_router() call."""


# Everything that isn't auth.
items = APIRouter(prefix="/items", tags=["items"])


@items.post("/", status_code=201)
def create_item(item: Item) -> dict[str, str]:
    """Add an item to the catalogue."""
    return {"name": item.name}


@items.get("/{item_id}")
def read_item(
    item_id: int,
    color: Color,
    x_request_id: Annotated[str, Header(description="Trace id")],
    verbose: bool = False,
    limit: Annotated[int, Query(ge=1, le=100, description="Page size")] = 10,
    q: str | None = None,
    labels: Annotated[list[str] | None, Query()] = None,
    x_debug: Annotated[str | None, Header()] = None,
) -> dict[str, int]:
    return {"id": item_id}


@items.get("/{item_id}/files/{name:path}")
def read_file(item_id: int, name: str) -> dict[str, str]:
    return {"name": name}


@items.post("/declared", summary="Example declared on the body")
def declared_body(
    payload: Annotated[
        dict[str, str],
        Body(openapi_examples={"normal": {"summary": "A normal one", "value": {"from": "openapi_examples"}}}),
    ],
    sort: Annotated[
        str, Query(openapi_examples={"newest": {"summary": "Newest first", "value": "-created"}})
    ] = "created",
) -> dict[str, str]:
    return payload


forms = APIRouter(prefix="/forms", tags=["forms"])


@forms.post("/contact")
def contact(
    subject: Annotated[str, Form(description="What it's about")], urgent: Annotated[bool, Form()] = False
) -> bool:
    return urgent


@forms.post("/upload")
def upload(
    title: Annotated[str, Form()],
    attachment: Annotated[UploadFile | None, File()] = None,
    extras: Annotated[list[UploadFile] | None, File()] = None,
) -> dict[str, str]:
    return {"title": title}


admin = FastAPI(title="Admin")


@admin.get("/stats", tags=["admin"])
def stats(key: Annotated[str, Depends(_HEADER_KEY)]) -> dict[str, int]:
    check(key)
    return {"users": 1}


app = FastAPI(title="Shop", version="2.1.0", description="A small shop.")
app.include_router(items)
app.include_router(forms)
app.include_router(secured)
app.include_router(reports)
app.include_router(audit, dependencies=[Depends(current_admin)])
app.include_router(auth)
app.mount("/admin", admin)


@app.api_route("/ping", methods=["GET", "POST"])
def ping() -> str:
    """Check the service is up."""
    return "pong"


@app.get("/hidden", include_in_schema=False)
def hidden() -> str:
    return "not for the docs"
