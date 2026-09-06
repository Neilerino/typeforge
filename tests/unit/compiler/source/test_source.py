from pathlib import Path

from typeforge.compiler.source import (
    MarkerKind,
    MarkerTypeExpression,
    parse_module,
    parse_source,
)


def test_parse_source_preserves_imported_marker_meaning() -> None:
    path = Path("example.py")

    result = (
        parse_source(
            "from typeforge import Each\ndef first[T](values: Each[T]) -> T: ...\n",
            path,
        )
        .unwrap()
        .source
    )

    annotation = result.functions[0].parameters[0].annotation

    assert isinstance(annotation, MarkerTypeExpression)
    assert annotation.marker is MarkerKind.EACH
    assert annotation.source == "Each[T]"
    assert annotation.span.path == path


def test_parse_module_reads_authored_module_without_executing_it(
    tmp_path: Path,
) -> None:
    path = tmp_path / "example.py"
    path.write_text(
        'raise RuntimeError("must not execute authored code")\n'
        "def choose(value: int) -> str: ...\n",
        encoding="utf-8",
    )

    module = parse_module(path).unwrap().source

    assert module.path == path
    assert tuple(function.name for function in module.functions) == ("choose",)
