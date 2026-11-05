"""The command line, pointed at real files laid out the way people lay out their projects."""

import json
import sys
from importlib import metadata
from pathlib import Path
from typing import Any

import pytest

from fastapi2postman.cli import main

ROUTER = """
from fastapi import APIRouter
router = APIRouter()
@router.get("/from-router")
def from_router(): ...
"""


@pytest.fixture(autouse=True)
def project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "path", sys.path[:])
    return tmp_path


def write(path: str, text: str = "") -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(text, encoding="utf-8")


def app_source(title: str = "T", variable: str = "app", extra: str = "") -> str:
    return f"from fastapi import FastAPI\n{extra}\n{variable} = FastAPI(title={title!r})\n"


def run(monkeypatch: pytest.MonkeyPatch, *args: str) -> dict[str, Any]:
    monkeypatch.setattr(sys, "argv", ["fastapi2postman", "--output", "out.json", *args])
    main()
    return json.loads(Path("out.json").read_text(encoding="utf-8"))


def fails(monkeypatch: pytest.MonkeyPatch, *args: str) -> str:
    with pytest.raises(SystemExit) as stopped:
        run(monkeypatch, *args)
    return str(stopped.value)


def test_file_with_the_default_attribute(monkeypatch: pytest.MonkeyPatch):
    write("plain_file.py", app_source("Plain"))
    assert run(monkeypatch, "--app", "plain_file.py")["info"]["name"] == "Plain"


def test_file_with_an_attribute(monkeypatch: pytest.MonkeyPatch):
    write("named_attr.py", app_source("Named", variable="api"))
    assert run(monkeypatch, "--app", "named_attr.py:api")["info"]["name"] == "Named"


def test_file_elsewhere_can_import_its_neighbours(monkeypatch: pytest.MonkeyPatch):
    write("service/neighbour_mod.py", "TITLE = 'Neighbour'\n")
    write("service/elsewhere.py", "import neighbour_mod\n" + app_source() + "app.title = neighbour_mod.TITLE\n")
    assert run(monkeypatch, "--app", "service/elsewhere.py")["info"]["name"] == "Neighbour"


def test_module_and_attribute_from_the_project_root(monkeypatch: pytest.MonkeyPatch):
    # A console script has its own directory on sys.path, not the current one, so this needs the cwd added.
    write("shop_a/__init__.py")
    write("shop_a/routers.py", ROUTER)
    write("shop_a/main.py", app_source(extra="from .routers import router") + "app.include_router(router)\n")
    collection = run(monkeypatch, "--app", "shop_a.main:app")
    assert collection["item"][0]["request"]["url"]["path"] == ["from-router"]


def test_module_without_an_attribute(monkeypatch: pytest.MonkeyPatch):
    write("shop_b/__init__.py")
    write("shop_b/main.py", app_source("Module"))
    assert run(monkeypatch, "--app", "shop_b.main")["info"]["name"] == "Module"


def test_file_inside_a_package_can_use_relative_imports(monkeypatch: pytest.MonkeyPatch):
    write("shop_c/__init__.py")
    write("shop_c/api/__init__.py")
    write("shop_c/api/routers.py", ROUTER)
    write("shop_c/api/main.py", app_source(extra="from .routers import router") + "app.include_router(router)\n")
    collection = run(monkeypatch, "--app", "shop_c/api/main.py")
    assert collection["item"][0]["request"]["url"]["path"] == ["from-router"]


def test_file_in_a_folder_without_init_can_import_from_the_project_root(monkeypatch: pytest.MonkeyPatch):
    write("shop_d/routers.py", ROUTER)
    write("shop_d/main.py", app_source(extra="from shop_d.routers import router") + "app.include_router(router)\n")
    collection = run(monkeypatch, "--app", "shop_d/main.py")
    assert collection["item"][0]["request"]["url"]["path"] == ["from-router"]


def test_the_given_file_beats_an_installed_module_of_the_same_name(monkeypatch: pytest.MonkeyPatch):
    write("installed/same_name_mod.py", app_source("Installed"))
    sys.path.insert(0, str(Path("installed").resolve()))
    write("same_name_mod.py", app_source("Mine"))
    assert run(monkeypatch, "--app", "same_name_mod.py")["info"]["name"] == "Mine"


def test_a_path_holding_a_colon_is_still_a_file(monkeypatch: pytest.MonkeyPatch):
    # Think of C:\project\app.py.
    write("colon:file.py", app_source("Colon"))
    assert run(monkeypatch, "--app", "colon:file.py")["info"]["name"] == "Colon"


def test_factory_function(monkeypatch: pytest.MonkeyPatch):
    write("factory_mod.py", "from fastapi import FastAPI\ndef create_app():\n    return FastAPI(title='Built')\n")
    assert run(monkeypatch, "--app", "factory_mod.py:create_app")["info"]["name"] == "Built"


@pytest.mark.parametrize("spec", ["nope_mod:app", "nope_pkg.main:app", "nope_mod", "nope_dir/nope.py"])
def test_something_that_cannot_be_found(monkeypatch: pytest.MonkeyPatch, spec: str):
    message = fails(monkeypatch, "--app", spec)
    assert "cannot find" in message
    assert spec.partition(":")[0] in message


def test_a_missing_attribute(monkeypatch: pytest.MonkeyPatch):
    write("no_attr_mod.py", app_source())
    assert "no attribute 'api'" in fails(monkeypatch, "--app", "no_attr_mod.py:api")


@pytest.mark.parametrize(("name", "source"), [("not_app_a", "app = 42\n"), ("not_app_b", "app = lambda: 42\n")])
def test_something_that_is_not_a_fastapi_app(monkeypatch: pytest.MonkeyPatch, name: str, source: str):
    write(f"{name}.py", source)
    message = fails(monkeypatch, "--app", f"{name}.py")
    assert "not a FastAPI app" in message
    assert "int" in message


def test_a_missing_dependency_of_the_app_is_not_reported_as_a_missing_app(monkeypatch: pytest.MonkeyPatch):
    write("broken_mod.py", "import not_installed_anywhere\n")
    with pytest.raises(ModuleNotFoundError, match="not_installed_anywhere"):
        run(monkeypatch, "--app", "broken_mod.py")


@pytest.mark.parametrize(
    ("flags", "expected"),
    [
        ([], "http://localhost:8000"),
        (["--host", "0.0.0.0"], "http://0.0.0.0:8000"),
        (["--port", "9000"], "http://localhost:9000"),
        (["--host", "api", "--port", "80"], "http://api:80"),
        (["--base-url", "https://api.example.com/"], "https://api.example.com"),
        (["--base-url", "https://api.example.com", "--port", "80"], "https://api.example.com"),
    ],
)
def test_where_the_requests_go(monkeypatch: pytest.MonkeyPatch, flags: list[str], expected: str):
    write("where_mod.py", app_source())
    assert run(monkeypatch, "--app", "where_mod.py", *flags)["variable"][0]["value"] == expected


def test_bearer_flag(monkeypatch: pytest.MonkeyPatch):
    write("bearer_mod.py", app_source())
    assert "auth" not in run(monkeypatch, "--app", "bearer_mod.py")
    assert run(monkeypatch, "--app", "bearer_mod.py", "--bearer")["auth"]["type"] == "bearer"


def test_collection_name(monkeypatch: pytest.MonkeyPatch):
    write("name_mod.py", app_source())
    assert run(monkeypatch, "--app", "name_mod.py", "--name", "Mine")["info"]["name"] == "Mine"


def test_output_is_utf8_and_readable(monkeypatch: pytest.MonkeyPatch):
    write("utf8_mod.py", app_source("Café"))
    run(monkeypatch, "--app", "utf8_mod.py")
    assert '"Café"' in Path("out.json").read_text(encoding="utf-8")


def test_reports_where_it_wrote_and_how_many_requests(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture):
    source = (
        app_source()
        + """
@app.get("/tagged", tags=["a"])
def tagged(): ...
@app.get("/untagged")
def untagged(): ...
"""
    )
    write("count_mod.py", source)
    run(monkeypatch, "--app", "count_mod.py")
    assert capsys.readouterr().out == "out.json: 2 requests\n"


def test_version_flag(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture):
    with pytest.raises(SystemExit) as stopped:
        run(monkeypatch, "--version")
    assert stopped.value.code == 0
    assert capsys.readouterr().out.strip() == metadata.version("fastapi2postman")
