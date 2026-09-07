"""Rewrite materialized record aliases throughout stub declarations."""

from dataclasses import replace
from typing import assert_never

from typeforge.compiler.record_materialization._models import DerivedRecord
from typeforge.compiler.stub_ir import (
    ClassDeclaration,
    Declaration,
    FunctionDeclaration,
    OverloadDeclaration,
    StubTypeExpression,
    TypeAliasDeclaration,
    TypeApplication,
    TypeName,
    TypeRewriteObserver,
    VariableDeclaration,
    rewrite_type,
)


class RecordAliasRewriter:
    """Bind record replacements and their observer once for a traversal."""

    def __init__(
        self,
        derived: tuple[DerivedRecord, ...],
        *,
        on_rewrite: TypeRewriteObserver | None = None,
    ) -> None:
        self._replacements = {
            (item.alias, item.input_name): item.shape.name or "object"
            for item in derived
        }
        self._on_rewrite = on_rewrite

    def rewrite_declaration(self, declaration: Declaration) -> Declaration:
        match declaration:
            case FunctionDeclaration() | OverloadDeclaration():
                return self._rewrite_callable(declaration)

            case TypeAliasDeclaration():
                return replace(declaration, value=self.rewrite_type(declaration.value))

            case VariableDeclaration():
                annotation = self.rewrite_type(declaration.annotation)
                return replace(declaration, annotation=annotation)

            case ClassDeclaration():
                return self._rewrite_class(declaration)

            case _ as unreachable:
                assert_never(unreachable)

    def rewrite_type(self, expression: StubTypeExpression) -> StubTypeExpression:
        return rewrite_type(
            expression, self._replace_alias, on_rewrite=self._on_rewrite
        )

    def _replace_alias(
        self, expression: StubTypeExpression
    ) -> StubTypeExpression | None:
        match expression:
            case TypeApplication(TypeName(alias), (TypeName(input_name),)):
                name = self._replacements.get((alias, input_name))
                # Each occurrence retains its own identity for authored origins.
                return TypeName(name) if name is not None else None

            case _:
                return None

    def _rewrite_function(
        self, declaration: FunctionDeclaration
    ) -> FunctionDeclaration:
        parameters = tuple(
            replace(parameter, annotation=self.rewrite_type(parameter.annotation))
            for parameter in declaration.parameters
        )
        return_type = self.rewrite_type(declaration.return_type)
        return replace(declaration, parameters=parameters, return_type=return_type)

    def _rewrite_callable(
        self, declaration: FunctionDeclaration | OverloadDeclaration
    ) -> FunctionDeclaration | OverloadDeclaration:
        match declaration:
            case FunctionDeclaration():
                return self._rewrite_function(declaration)

            case OverloadDeclaration():
                signatures = tuple(
                    self._rewrite_function(signature)
                    for signature in declaration.signatures
                )
                fallback = self._rewrite_function(declaration.fallback)
                return replace(declaration, signatures=signatures, fallback=fallback)

    def _rewrite_class(self, declaration: ClassDeclaration) -> ClassDeclaration:
        bases = tuple(self.rewrite_type(base) for base in declaration.bases)
        fields = tuple(
            replace(field, annotation=self.rewrite_type(field.annotation))
            for field in declaration.fields
        )
        methods = tuple(
            self._rewrite_callable(method) for method in declaration.methods
        )
        return replace(declaration, bases=bases, fields=fields, methods=methods)
