from dataclasses import dataclass
from typing import Protocol


class _JsonSchemaHandler(Protocol):
    def __call__(self, core_schema: object) -> dict[str, object]: ...


@dataclass(frozen=True, slots=True)
class Doc:
    """Attach Markdown documentation to an ``Annotated`` type.

    ```python
    type UserId = Annotated[int, Doc("A stable user identifier.")]
    ```
    """

    documentation: str

    def __get_pydantic_json_schema__(
        self,
        core_schema: object,
        handler: _JsonSchemaHandler,
    ) -> dict[str, object]:
        return {**handler(core_schema), "description": self.documentation}
