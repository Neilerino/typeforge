"""Source annotation analysis for imports required by adaptation."""

from typeforge.compiler.source import SourceModule
from typeforge.compiler.stub_ir import ImportFrom


def annotation_imports(module: SourceModule) -> tuple[ImportFrom, ...]:
    all_functions = (
        *module.functions,
        *(method for source_class in module.classes for method in source_class.methods),
    )
    if any(
        function.returns is None
        or any(parameter.annotation is None for parameter in function.parameters)
        for function in all_functions
    ):
        return (ImportFrom("typing", ("Any",)),)

    return ()
