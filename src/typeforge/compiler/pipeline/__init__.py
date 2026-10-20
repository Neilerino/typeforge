"""Public compilation, projection, and implementation-verification interface."""

from typeforge.compiler.adaptation import (
    AdaptationError,
)
from typeforge.compiler.emission import EmissionError
from typeforge.compiler.module_surface import UnsupportedPublicDeclaration
from typeforge.compiler.pipeline._callables import (
    describe_authored_callables,
    describe_callable_annotations,
    describe_type_parameter_projections,
)
from typeforge.compiler.pipeline._compilation import compile_source
from typeforge.compiler.pipeline._generation import generate_module
from typeforge.compiler.pipeline._models import (
    AnnotationProjection,
    AuthoredCallable,
    AuthoredParameter,
    AuthoredParameterKind,
    CompilationError,
    CompilationPlan,
    GeneratedModule,
    GenerationError,
    TypeParameterProjection,
)
from typeforge.compiler.record_materialization import (
    RecordMaterializationError,
)
from typeforge.compiler.source import SourceSpan, SourceSyntaxError
from typeforge.compiler.specialization import LoweringError, checker_type_bound
from typeforge.compiler.verification import ImplicitReturnSite, VerificationPlan

__all__ = [
    "AdaptationError",
    "AnnotationProjection",
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
    "TypeParameterProjection",
    "UnsupportedPublicDeclaration",
    "VerificationPlan",
    "checker_type_bound",
    "compile_source",
    "describe_authored_callables",
    "describe_callable_annotations",
    "describe_type_parameter_projections",
    "generate_module",
]
