"""Import normalization for stub modules."""

from typeforge.compiler.stub_ir._model import Import, ImportFrom, ModuleImport


def merge_imports(imports: tuple[ModuleImport, ...]) -> tuple[ModuleImport, ...]:
    module_imports = tuple(
        dict.fromkeys(item for item in imports if isinstance(item, Import))
    )
    merged: dict[str, set[str]] = {}
    for item in imports:
        if isinstance(item, Import):
            continue
        merged.setdefault(item.module, set()).update(item.names)
    return (
        *module_imports,
        *(ImportFrom(module, tuple(sorted(names))) for module, names in merged.items()),
    )
