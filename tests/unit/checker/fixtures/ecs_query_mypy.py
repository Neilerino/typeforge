from typing import assert_type

from ecs_api import Option, Position, Velocity, World

world = World[int]()

assert_type(
    world.query(Position, Velocity),
    tuple[int, Position, Velocity] | None,
)
assert_type(
    world.query(Position, Option[Velocity]),
    tuple[int, Position, Velocity | None] | None,
)
