import ast
from pathlib import Path
from sys import executable
from typing import cast

from typeforge.analysis.model import SourceSpan, VirtualDocument
from typeforge.proxy.model import JsonObject, ProxyConfiguration


def pyrefly_proxy_configuration(
    project_root: Path,
    backend_command: tuple[str, ...] = (
        str(Path(executable).with_name("pyrefly")),
        "lsp",
    ),
    maximum_arity: int = 8,
) -> ProxyConfiguration:
    return ProxyConfiguration(
        project_root=project_root,
        backend_command=backend_command,
        maximum_arity=maximum_arity,
        initialize=configure_pyrefly_initialize,
        suppress_diagnostic=suppress_pyrefly_artifact,
    )


def configure_pyrefly_initialize(message: JsonObject) -> JsonObject:
    parameters = object_value(message.get("params"))
    if parameters is None:
        return message
    options = object_value(parameters.get("initializationOptions")) or {}
    pyrefly = object_value(options.get("pyrefly")) or {}
    configured_pyrefly: JsonObject = {
        **pyrefly,
        "typeCheckingMode": "strict",
        "disableTypeErrors": False,
        "analysis": {"showHoverGoToLinks": False},
    }
    configured_options: JsonObject = {
        **options,
        "pythonPath": executable,
        "pyrefly": configured_pyrefly,
    }
    return {
        **message,
        "params": {**parameters, "initializationOptions": configured_options},
    }


def suppress_pyrefly_artifact(
    diagnostic: JsonObject,
    document: VirtualDocument,
    span: SourceSpan,
) -> bool:
    if diagnostic.get("code") != "unused-import":
        return False
    lines = document.authored_text.splitlines()
    if (
        span.start.line >= len(lines)
        or "from typeforge import" not in lines[span.start.line]
    ):
        return False
    try:
        tree = ast.parse(document.authored_text, type_comments=True)
    except SyntaxError:
        return False
    imported = document.authored_text[span.start.offset : span.end.offset]
    if not imported.isidentifier():
        return False
    return any(
        isinstance(node, ast.Name)
        and isinstance(node.ctx, ast.Load)
        and node.id == imported
        for node in ast.walk(tree)
    )


def object_value(value: object) -> JsonObject | None:
    return cast(JsonObject, value) if isinstance(value, dict) else None
