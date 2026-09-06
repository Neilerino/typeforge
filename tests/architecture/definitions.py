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
        ArchFile(name="map_evaluation"),
        ArchFile(name="evaluation"),
    ],
)


TYPE_FORGE = ArchModule(
    name="typeforge",
    sub_modules=[
        SEMANTICS,
        ArchModule(
            name="compiler",
            sub_modules=[
                ArchModule(name="source"),
                ArchModule(name="adaptation"),
                ArchModule(name="specialization"),
                ArchModule(name="record_materialization"),
                ArchModule(name="pipeline"),
            ],
        ),
        ArchModule(name="overlay"),
        ArchModule(name="diagnostics"),
    ],
)
