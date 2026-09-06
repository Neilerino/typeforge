"""Create target-neutral compilation plans from authored source."""

from pathlib import Path

from returns.result import Result

from typeforge.compiler.adaptation import AdaptationError, adapt_source_module
from typeforge.compiler.pipeline._models import CompilationError, CompilationPlan
from typeforge.compiler.record_materialization import RecordMaterializationError
from typeforge.compiler.source import SourceModule, parse_source
from typeforge.compiler.specialization import (
    ArityFrontier,
    LoweringError,
    lower_variadic_module,
)


def compile_source(
    source: str,
    path: Path,
    maximum_arity: int,
) -> Result[CompilationPlan, CompilationError]:
    return Result.do(
        plan
        for parsed in parse_source(source, path)
        for plan in compile_module(parsed.source, maximum_arity=maximum_arity)
    )


def compile_module(
    source: SourceModule,
    maximum_arity: int,
) -> Result[
    CompilationPlan, AdaptationError | RecordMaterializationError | LoweringError
]:
    return Result.do(
        CompilationPlan(source, specialized)
        for adapted in adapt_source_module(source)
        for specialized in lower_variadic_module(
            adapted,
            ArityFrontier(0, maximum_arity),
        )
    )
