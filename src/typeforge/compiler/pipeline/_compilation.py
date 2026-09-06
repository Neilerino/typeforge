"""Create target-neutral compilation plans from authored source."""

from pathlib import Path

from returns.result import Result

from typeforge.compiler.adaptation import AdaptationError, adapt_source_module
from typeforge.compiler.pipeline._models import CompilationError, CompilationPlan
from typeforge.compiler.record_materialization import RecordMaterializationError
from typeforge.compiler.source import ParsedSource, parse_source
from typeforge.compiler.specialization import (
    ArityFrontier,
    LoweringError,
    lower_variadic_module,
)
from typeforge.compiler.verification import analyze_implementations


def compile_source(
    source: str,
    path: Path,
    maximum_arity: int,
) -> Result[CompilationPlan, CompilationError]:
    return Result.do(
        plan
        for parsed in parse_source(source, path)
        for plan in compile_module(parsed, maximum_arity=maximum_arity)
    )


def compile_module(
    parsed: ParsedSource,
    maximum_arity: int,
) -> Result[
    CompilationPlan, AdaptationError | RecordMaterializationError | LoweringError
]:
    return Result.do(
        CompilationPlan(
            source=parsed.source,
            module=specialized,
            verification=analyze_implementations(parsed, specialized),
        )
        for adapted in adapt_source_module(parsed.source)
        for specialized in lower_variadic_module(
            adapted,
            ArityFrontier(0, maximum_arity),
        )
    )
