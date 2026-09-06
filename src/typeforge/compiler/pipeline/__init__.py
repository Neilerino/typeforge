"""Public compilation, projection, and implementation-verification interface."""

from typeforge.compiler.adaptation import (
    AdaptationError,
)
from typeforge.compiler.emission import EmissionError
from typeforge.compiler.module_surface import UnsupportedPublicDeclaration
from typeforge.compiler.pipeline._callables import describe_authored_callables
from typeforge.compiler.pipeline._compilation import compile_source
from typeforge.compiler.pipeline._generation import generate_module
from typeforge.compiler.pipeline._models import (
    AuthoredCallable,
    AuthoredParameter,
    AuthoredParameterKind,
    CompilationError,
    CompilationPlan,
    GeneratedModule,
    GenerationError,
)
from typeforge.compiler.record_materialization import (
    RecordMaterializationError,
)
from typeforge.compiler.source import SourceSpan, SourceSyntaxError
from typeforge.compiler.specialization import LoweringError
from typeforge.compiler.verification import ImplicitReturnSite, VerificationPlan

__all__ = [
    "AdaptationError",
    "AuthoredCallable",
    "AuthoredParameter",
    "AuthoredParameterKind",
    "CompilationError",
    "CompilationPlan",
    "EmissionError",
    "GeneratedModule",
    "GenerationError",
    "ImplicitReturnSite",
    "LoweringError",
    "RecordMaterializationError",
    "SourceSpan",
    "SourceSyntaxError",
    "UnsupportedPublicDeclaration",
    "VerificationPlan",
    "compile_source",
    "describe_authored_callables",
    "generate_module",
]
