from returns.result import Failure, Result, Success


def reciprocal(value: int) -> Result[float, str]:
    if value == 0:
        return Failure("division by zero")
    return Success(1 / value)


def test_result_represents_success() -> None:
    assert reciprocal(2) == Success(0.5)


def test_result_represents_expected_failure() -> None:
    assert reciprocal(0) == Failure("division by zero")
