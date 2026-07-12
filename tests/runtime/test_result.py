from typeforge._result import Err, Ok, Result


def reciprocal(value: int) -> Result[float, str]:
    if value == 0:
        return Err("division by zero")
    return Ok(1 / value)


def test_result_represents_success() -> None:
    assert reciprocal(2) == Ok(0.5)


def test_result_represents_expected_failure() -> None:
    assert reciprocal(0) == Err("division by zero")
