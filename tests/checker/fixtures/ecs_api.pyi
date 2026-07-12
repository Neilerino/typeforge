from typing import overload

class Position: ...
class Velocity: ...
class Option[T]: ...

class World[E]:
    @overload
    def query[T1](
        self,
        component_1: type[Option[T1]],
    ) -> tuple[E, T1 | None] | None: ...
    @overload
    def query[T1](
        self,
        component_1: type[T1],
    ) -> tuple[E, T1] | None: ...
    @overload
    def query[T1, T2](
        self,
        component_1: type[Option[T1]],
        component_2: type[Option[T2]],
    ) -> tuple[E, T1 | None, T2 | None] | None: ...
    @overload
    def query[T1, T2](
        self,
        component_1: type[Option[T1]],
        component_2: type[T2],
    ) -> tuple[E, T1 | None, T2] | None: ...
    @overload
    def query[T1, T2](
        self,
        component_1: type[T1],
        component_2: type[Option[T2]],
    ) -> tuple[E, T1, T2 | None] | None: ...
    @overload
    def query[T1, T2](
        self,
        component_1: type[T1],
        component_2: type[T2],
    ) -> tuple[E, T1, T2] | None: ...
    @overload
    def query[T](
        self,
        *components: type[T] | type[Option[T]],
    ) -> tuple[E, *tuple[T | None, ...]] | None: ...
