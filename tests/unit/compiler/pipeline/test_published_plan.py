import ast
from pathlib import Path
from textwrap import dedent
from unittest.mock import patch

from pytest import MonkeyPatch
from returns.result import Failure, Success

from typeforge.compiler.pipeline import (
    AdaptationError,
    UnsupportedPublicDeclaration,
    _compilation,
    compile_source,
    generate_module,
)
from typeforge.compiler.source import SourceModule, SourceReadError, SourceSyntaxError
from typeforge.compiler.specialization import LoweringError, LoweringErrorCode
from typeforge.compiler.stub_ir import MapType, TypeAliasDeclaration


def test_published_generation_uses_the_compilers_adaptation_and_preserves_failure(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    path = tmp_path / "identity.py"
    source = "def identity[T](value: T) -> T: ...\n"
    path.write_text(source, encoding="utf-8")
    error = AdaptationError("identity", "T", "cannot adapt this annotation")

    def reject_annotation(module: SourceModule) -> Failure[AdaptationError]:
        assert module.path == path
        assert module.functions[0].name == "identity"
        return Failure(error)

    monkeypatch.setattr(_compilation, "adapt_source_module", reject_annotation)

    # An invalid frontier would fail if compilation continued after adaptation.
    compiled = compile_source(source, path, maximum_arity=-1)
    published = generate_module(path, maximum_arity=-1)

    assert isinstance(compiled, Failure)
    assert compiled.failure() is error
    assert isinstance(published, Failure)
    assert published.failure() is error


def test_relationship_aliases_remain_target_neutral_until_publication(
    tmp_path: Path,
) -> None:
    path = tmp_path / "wire.py"
    source = dedent("""        from typeforge import Map

        type Wire[T] = Map[T, bytes : str, ... : int]
        """)
    path.write_text(source, encoding="utf-8")

    plan = compile_source(source, path, maximum_arity=1).unwrap()
    published = generate_module(path, maximum_arity=1).unwrap()

    (alias,) = plan.module.declarations
    assert isinstance(alias, TypeAliasDeclaration)
    assert isinstance(alias.value, MapType)
    assert published.source_path == plan.source.path == path
    assert published.content == "type Wire[T] = object\n"


def test_runtime_statements_are_accepted_by_compilation_but_rejected_for_publication(
    tmp_path: Path,
) -> None:
    path = tmp_path / "application.py"
    source = dedent("""\
        while ready():
            serve()
        """)
    path.write_text(source, encoding="utf-8")

    compiled = compile_source(source, path, maximum_arity=1)
    published = generate_module(path, maximum_arity=1)

    assert isinstance(compiled, Success)
    assert compiled.unwrap().module.declarations == ()
    assert isinstance(published, Failure)
    error = published.failure()
    assert isinstance(error, UnsupportedPublicDeclaration)
    assert error.path == path
    assert error.line == 1


def test_public_surface_failure_precedes_compiler_failures(tmp_path: Path) -> None:
    path = tmp_path / "invalid_application.py"
    source = dedent("""        from typeforge import Equal, Map

        def choose[T](value: T) -> Map[T, Equal[T, int, str] : str]: ...

        while ready():
            serve()
        """)
    path.write_text(source, encoding="utf-8")

    compiled = compile_source(source, path, maximum_arity=-1)
    published = generate_module(path, maximum_arity=-1)

    assert isinstance(compiled, Failure)
    assert isinstance(compiled.failure(), AdaptationError)
    assert isinstance(published, Failure)
    error = published.failure()
    assert isinstance(error, UnsupportedPublicDeclaration)
    assert error.line == 5


def test_specialization_failures_are_preserved_for_publication(tmp_path: Path) -> None:
    path = tmp_path / "identity.py"
    source = "def identity[T](value: T) -> T: ...\n"
    path.write_text(source, encoding="utf-8")

    compiled = compile_source(source, path, maximum_arity=-1)
    published = generate_module(path, maximum_arity=-1)

    assert isinstance(compiled, Failure)
    error = compiled.failure()
    assert isinstance(error, LoweringError)
    assert error.code == LoweringErrorCode.INVALID_FRONTIER
    assert published == compiled


def test_syntax_failure_precedes_public_surface_validation(tmp_path: Path) -> None:
    path = tmp_path / "invalid.py"
    source = "while ready():\n    serve()\ndef broken(\n"
    path.write_text(source, encoding="utf-8")

    compiled = compile_source(source, path, maximum_arity=-1)
    published = generate_module(path, maximum_arity=-1)

    assert isinstance(compiled, Failure)
    error = compiled.failure()
    assert isinstance(error, SourceSyntaxError)
    assert error.path == path
    assert published == compiled


def test_missing_source_is_a_modeled_read_failure(tmp_path: Path) -> None:
    path = tmp_path / "missing.py"

    published = generate_module(path, maximum_arity=1)

    assert isinstance(published, Failure)
    error = published.failure()
    assert isinstance(error, SourceReadError)
    assert error.path == path


def test_publication_reads_and_parses_the_authored_module_once(tmp_path: Path) -> None:
    path = tmp_path / "snapshot.py"
    source = dedent("""\
        from external import Parser
        answer = 42  # type: int
        def identity[T](value: T) -> T: ...
        """)
    path.write_text(source, encoding="utf-8")

    with (
        patch.object(Path, "read_text", autospec=True, return_value=source) as read,
        patch("ast.parse", wraps=ast.parse) as parse,
    ):
        published = generate_module(path, maximum_arity=2).unwrap()

    assert published.content == dedent("""\
        from external import Parser

        answer: int

        def identity[T](value: T) -> T: ...
        """)
    assert read.call_args_list == [((path,), {"encoding": "utf-8"})]
    module_parses = [
        call
        for call in parse.call_args_list
        if call.kwargs.get("mode", "exec") == "exec"
    ]
    assert len(module_parses) == 1
    assert module_parses[0].args == (source,)
