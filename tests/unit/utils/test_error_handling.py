from dataclasses import dataclass

import pytest
from returns.maybe import Nothing
from returns.primitives.exceptions import UnwrapFailedError
from returns.result import Failure, Result, Success

from typeforge.utils.error_handling import safe_result


class DomainError(Exception):
    pass


@dataclass(frozen=True)
class ErrorDetails:
    message: str


def test_success_preserves_arguments_and_value_identity() -> None:
    value = object()

    @safe_result(errors=(DomainError,))
    def operation(number: int, *, label: str) -> object:
        assert (number, label) == (42, "answer")
        return value

    result: Result[object, DomainError] = operation(42, label="answer")

    assert result.unwrap() is value
    assert operation.__name__ == "operation"


@pytest.mark.parametrize("nested", [False, True], ids=["raised", "unwrapped"])
def test_modeled_exception_is_returned_by_identity(nested: bool) -> None:
    error = DomainError("cannot continue")

    @safe_result(errors=(DomainError,))
    def operation() -> None:
        if nested:
            Failure(error).unwrap()

        raise error

    assert operation().failure() is error


def test_unwrapped_error_data_short_circuits_the_operation() -> None:
    error = ErrorDetails("cannot render")
    visited: list[str] = []

    @safe_result(errors=(ErrorDetails,))
    def operation() -> str:
        visited.append("first step")
        value: str = Failure(error).unwrap()
        visited.append("second step")
        return value

    result: Result[str, ErrorDetails] = operation()

    assert result.failure() is error
    assert visited == ["first step"]


def test_a_seam_can_declare_exception_and_data_failures() -> None:
    errors: tuple[type[DomainError | ErrorDetails], ...] = (DomainError, ErrorDetails)

    @safe_result(errors=errors)
    def operation(result: Result[int, DomainError | ErrorDetails]) -> int:
        return result.unwrap()

    for error in (DomainError("domain"), ErrorDetails("details")):
        result: Result[int, DomainError | ErrorDetails] = operation(Failure(error))
        assert result.failure() is error

    assert operation(Success(42)).unwrap() == 42


def test_unexpected_exception_propagates_unchanged() -> None:
    error = RuntimeError("bug")

    @safe_result(errors=(DomainError,))
    def operation() -> None:
        raise error

    with pytest.raises(RuntimeError) as raised:
        operation()

    assert raised.value is error


@pytest.mark.parametrize(
    "error",
    [RuntimeError("bug"), ErrorDetails("wrong seam")],
    ids=["exception", "data"],
)
def test_unexpected_nested_failure_preserves_its_unwrap_error(error: object) -> None:
    with pytest.raises(UnwrapFailedError) as original:
        Failure(error).unwrap()

    @safe_result(errors=(DomainError,))
    def operation() -> None:
        raise original.value

    with pytest.raises(UnwrapFailedError) as raised:
        operation()

    assert raised.value is original.value


def test_unwrapping_nothing_is_not_a_modeled_result_failure() -> None:
    with pytest.raises(UnwrapFailedError) as original:
        Nothing.unwrap()

    @safe_result(errors=(DomainError,))
    def operation() -> None:
        raise original.value

    with pytest.raises(UnwrapFailedError) as raised:
        operation()

    assert raised.value is original.value
