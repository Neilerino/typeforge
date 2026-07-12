from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Doc:
    """Attach Markdown documentation to an ``Annotated`` type.

    ```python
    type UserId = Annotated[int, Doc("A stable user identifier.")]
    ```
    """

    documentation: str
