"""Data models for describing source modules in architecture tests."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from functools import cached_property
from pathlib import Path

from .consts import SOURCE_PATH


@dataclass
class ArchFile:
    """A named Python source file used by an architecture rule."""

    name: str
    module: ArchModule = field(init=False, repr=False, compare=False)

    @property
    def private(self) -> bool:
        """Whether this is a private implementation file."""
        return self.name.startswith("_") and self.name != "__init__"

    @cached_property
    def path(self) -> Path:
        """The file's path within its containing module."""
        return self.module.path / f"{self.name}.py"

    @cached_property
    def pattern(self) -> re.Pattern[str]:
        """Match this file's absolute path exactly."""
        return re.compile(rf"^{re.escape(self.path.as_posix())}$")


@dataclass
class ArchModule:
    """A Python package and the source files and packages it contains."""

    name: str
    sub_modules: list[ArchModule] = field(default_factory=list)
    files: list[ArchFile] = field(default_factory=list)
    parent: ArchModule | None = field(
        default=None, init=False, repr=False, compare=False
    )

    def __post_init__(self) -> None:
        for module in self.sub_modules:
            module.parent = self

        for file in self.files:
            file.module = self

    @property
    def private_files(self) -> list[ArchFile]:
        return [file for file in self.files if file.private]

    @cached_property
    def path(self) -> Path:
        if self.parent is None:
            return SOURCE_PATH / self.name

        return self.parent.path / self.name

    @cached_property
    def interface(self) -> ArchFile:
        interface = ArchFile(name="__init__")
        interface.module = self
        return interface

    @cached_property
    def pattern(self) -> re.Pattern[str]:
        return re.compile(rf"^{re.escape(self.path.as_posix())}/.*\.py$")

    @cached_property
    def implementation_pattern(self) -> re.Pattern[str]:
        """Match this package except for its public ``__init__.py`` interface."""
        return re.compile(
            rf"^{re.escape(self.path.as_posix())}/(?!__init__\.py$).*\.py$"
        )

    def files_outside(self, module: ArchModule) -> re.Pattern[str]:
        """Match files in this package that do not belong to ``module``."""
        try:
            relative_path = module.path.relative_to(self.path)
        except ValueError as error:
            raise ValueError(
                f"Module {module.name} is not inside {self.name}"
            ) from error

        return re.compile(
            rf"^{re.escape(self.path.as_posix())}/"
            rf"(?!{re.escape(relative_path.as_posix())}(?:/|$)).*\.py$"
        )

    @property
    def layers(self) -> list[ArchModule | ArchFile]:
        """Return layers ordered from most specific to least specific."""
        if not self.sub_modules:
            return [self]

        layers = [layer for module in self.sub_modules for layer in module.layers]

        if self.parent is None:
            return [*layers, self]

        return [*layers, *self.files, self.interface]

    def mod(self, name: str) -> ArchModule:
        """Return a descendant package by its dot-separated name."""
        current_module = self
        for part in name.split("."):
            try:
                current_module = next(
                    module
                    for module in current_module.sub_modules
                    if module.name == part
                )
            except StopIteration as error:
                raise ValueError(
                    f"Module {name} does not exist or is not registered"
                ) from error

        return current_module

    def file(self, name: str) -> ArchFile:
        """Return a source file in this package or a descendant package."""
        module_name, separator, file_name = name.rpartition(".")
        if separator:
            return self.mod(module_name).file(file_name)

        try:
            return next(file for file in self.files if file.name == file_name)
        except StopIteration as error:
            raise ValueError(
                f"File {name} does not exist or is not registered"
            ) from error
