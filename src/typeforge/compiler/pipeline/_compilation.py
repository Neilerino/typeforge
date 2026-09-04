"""Create target-neutral compilation plans from authored source."""

from pathlib import Path

from returns.result import Result

from typeforge.compiler.adaptation import adapt_source_module
from typeforge.compiler.pipeline._models import CompilationError, CompilationPlan
from typeforge.compiler.source import parse_source
from typeforge.compiler.specialization import ArityFrontier, lower_variadic_module


def compile_source(
    source: str,
    path: Path,
    maximum_arity: int,
) -> Result[CompilationPlan, CompilationError]:
    return Result.do(
        CompilationPlan(parsed, specialized)
        for parsed in parse_source(source, path)
        for adapted in adapt_source_module(parsed)
        for specialized in lower_variadic_module(
            adapted,
            ArityFrontier(0, maximum_arity),
        )
    )
