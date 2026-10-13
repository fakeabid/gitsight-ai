import ast
from pathlib import Path

import pytest

APP = Path(__file__).parents[1] / "app"
LLM_LIBS = {"langgraph", "langchain_core", "langchain_google_genai"}
FORBIDDEN = {
    "schemas": LLM_LIBS | {"fastapi", "app.domain", "app.graph", "app.services", "app.api"},
    "domain": LLM_LIBS | {"fastapi", "app.graph", "app.services", "app.api"},
    "graph": {"fastapi", "app.services", "app.api"},
    "services": {"fastapi", "app.api"},
    "api": LLM_LIBS | {"app.graph", "app.domain"},
}


def imported_modules(path: Path) -> set[str]:
    found: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            found.add(node.module)
    return found


@pytest.mark.parametrize("layer", FORBIDDEN)
def test_layer_respects_the_dependency_rule(layer):
    for file in (APP / layer).rglob("*.py"):
        for module in imported_modules(file):
            for banned in FORBIDDEN[layer]:
                assert (
                    module != banned and not module.startswith(banned + ".")
                ), f"{file}: {module}"
