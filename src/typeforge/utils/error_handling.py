from returns.result import Failure, Result


def ok[T, E: Exception](result: Result[T, E]) -> T:
    if isinstance(result, Failure):
        raise result.failure()
    return result.unwrap()
