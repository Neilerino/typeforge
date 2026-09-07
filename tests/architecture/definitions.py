"""Source-module definitions shared by architecture tests.

The semantics package is structured as an inward-facing dependency stack:
interfaces delegate to evaluation and protocols, which depend on domain data.
"""

from enum import StrEnum

from .helpers import ArchFile, ArchModule


class CoreModules(StrEnum):
    SEMANTICS = "semantics"


SEMANTICS = ArchModule(
    name=CoreModules.SEMANTICS.value,
    sub_modules=[
        ArchModule(
            name="domain",
            files=[
                ArchFile(name="assertions"),
                ArchFile(name="exceptions"),
                ArchFile(name="models"),
            ],
        )
    ],
    files=[
        ArchFile(name="protocols"),
        ArchFile(name="type_evaluation"),
        ArchFile(name="map_matching"),
        ArchFile(name="evaluation"),
    ],
)


TYPE_FORGE = ArchModule(
    name="typeforge",
    sub_modules=[
        SEMANTICS,
        ArchModule(
            name="pydantic",
            files=[
                ArchFile(name="_schema"),
                ArchFile(name="_annotation"),
                ArchFile(name="_compile"),
                ArchFile(name="_frontend"),
                ArchFile(name="_policy"),
                ArchFile(name="_type_system"),
                ArchFile(name="_records"),
                ArchFile(name="_emission"),
                ArchFile(name="_errors"),
            ],
        ),
        ArchModule(
            name="compiler",
            sub_modules=[
                ArchModule(name="source"),
                ArchModule(
                    name="adaptation",
                    files=[
                        ArchFile(name="_schema"),
                        ArchFile(name="_schema_aliases"),
                        ArchFile(name="_source_to_ir"),
                    ],
                ),
                ArchModule(name="semantic_adapter", files=[ArchFile(name="_emission")]),
                ArchModule(name="specialization"),
                ArchModule(name="record_materialization"),
                ArchModule(name="pipeline"),
                ArchModule(name="verification"),
                ArchModule(name="module_surface"),
                ArchModule(name="stub_ir"),
                ArchModule(name="emission"),
            ],
        ),
        ArchModule(name="overlay"),
        ArchModule(name="diagnostics"),
        ArchModule(name="analysis"),
        ArchModule(name="adapters"),
        ArchModule(name="proxy"),
        ArchModule(name="utils", files=[ArchFile(name="error_handling")]),
    ],
    files=[ArchFile(name="cli")],
)
