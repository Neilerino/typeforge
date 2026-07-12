from enum import Enum as _Enum

class ExecutionMode(_Enum):
    RUNTIME = ...
    AST_ONLY = ...
    AUTO = ...

class StubConfig:
    execution_mode: ExecutionMode
    include_private: bool
    respect_all: bool
    verbose: bool
    strict: bool

    def __init__(
        self,
        execution_mode: ExecutionMode = ...,
        include_private: bool = ...,
        respect_all: bool = ...,
        verbose: bool = ...,
        strict: bool = ...,
    ) -> None: ...

class StubContext:
    config: StubConfig

    def __init__(self, *, config: StubConfig = ...) -> None: ...

def generate_stub(
    filepath: str,
    output_path: str | None = ...,
    ctx: StubContext | None = ...,
) -> str: ...
