"""Deterministic collision avoidance for generated record declarations."""


def available_record_name(stem: str, occupied: set[str]) -> str:
    name = stem
    index = 2
    while name in occupied:
        name = f"{stem}_{index}"
        index += 1

    return name
