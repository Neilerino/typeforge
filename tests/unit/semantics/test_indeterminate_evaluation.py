"""Three-way decisions through the shared evaluate() interface."""

import pytest
from returns.result import Failure, Result, Success

from tests.unit.semantics.test_migration_spec import (
    AdapterOperation,
    FailureInjectionTypeSystemProxy,
    NameTypeSystem,
)
from typeforge import semantics as s

ITEM = s.CaptureReference(s.TypeSymbol((__name__,), "Item"))


def test_equal_preserves_symbol_identity_and_uncertainty() -> None:
    symbol = s.TypeSymbol(scope=("models", "Payload"), name="T")
    value = s.TypeValueReference(s.UnresolvedType("T", symbol))

    assert s.evaluate(s.EqualExpression(value, value), NameTypeSystem()) == Success(
        True
    )
    assert s.evaluate(
        s.EqualExpression(value, s.TypeReference("int")), NameTypeSystem()
    ) == Success(s.IndeterminateCondition())


def unknown(name: str = "T") -> s.TypeValueReference[str]:
    return s.TypeValueReference(
        s.UnresolvedType(name, s.TypeSymbol(("models", "Payload"), name))
    )


def condition(value: bool | None) -> s.Expression[str]:
    if value is None:
        return s.EqualExpression(unknown(), s.TypeReference("int"))

    return s.EqualExpression(
        s.TypeReference("int"), s.TypeReference("int" if value else "str")
    )


@pytest.mark.parametrize(
    ("left", "right", "all_result", "any_result"),
    (
        (True, True, True, True),
        (True, False, False, True),
        (True, None, None, True),
        (False, True, False, True),
        (False, False, False, False),
        (False, None, False, None),
        (None, True, None, True),
        (None, False, False, None),
        (None, None, None, None),
    ),
)
def test_condition_truth_tables(
    left: bool | None,
    right: bool | None,
    all_result: bool | None,
    any_result: bool | None,
) -> None:
    operands = (condition(left), condition(right))
    assert s.evaluate(s.AllExpression(operands), NameTypeSystem()) == Success(
        s.IndeterminateCondition() if all_result is None else all_result
    )
    assert s.evaluate(s.AnyExpression(operands), NameTypeSystem()) == Success(
        s.IndeterminateCondition() if any_result is None else any_result
    )


def structure(origin: str, *arguments: s.TypeValue[str]) -> s.UnresolvedType[str]:
    return s.UnresolvedType(
        origin
        + "["
        + ", ".join(
            argument.value
            if isinstance(argument, s.ResolvedType | s.UnresolvedType)
            else argument.possible_output.value
            for argument in arguments
        )
        + "]",
        s.ParameterizedTypeShape(s.ResolvedType(origin), arguments),
    )


def test_partial_structural_equality_preserves_known_mismatches() -> None:
    left = s.TypeValueReference(
        structure("tuple", unknown().value, s.ResolvedType("int"))
    )
    right = s.TypeValueReference(
        structure("tuple", s.ResolvedType("str"), s.ResolvedType("bytes"))
    )

    assert s.evaluate(s.EqualExpression(left, left), NameTypeSystem()) == Success(True)
    assert s.evaluate(s.EqualExpression(left, right), NameTypeSystem()) == Success(
        False
    )


def test_uncertain_case_stops_at_the_next_definite_match() -> None:
    expression = s.MapExpression(
        s.TypeReference("int"),
        (
            s.CaseExpression(condition(None), s.TypeReference("str")),
            s.CaseExpression(s.TypeReference("int"), s.TypeReference("float")),
            s.CaseExpression(condition(None), s.KeyReference()),
        ),
        s.KeyReference(),
    )

    assert s.evaluate(expression, NameTypeSystem()) == Success(
        s.IndeterminateType(
            s.ResolvedType("str | float"),
            (s.ResolvedType("str"), s.ResolvedType("float")),
        )
    )


class BuildingTypeSystem(NameTypeSystem):
    def build(
        self, shape: s.ParameterizedTypeShape[str]
    ) -> Result[str, s.SemanticIssue]:
        return Success(f"{shape.origin}[{', '.join(shape.arguments)}]")


@pytest.mark.parametrize("value", (True, False, None))
def test_not_preserves_unknown(value: bool | None) -> None:
    expected = s.IndeterminateCondition() if value is None else not value
    assert s.evaluate(s.NotExpression(condition(value)), NameTypeSystem()) == Success(
        expected
    )


@pytest.mark.parametrize("kind", (s.AllExpression, s.AnyExpression))
def test_decisive_conditions_skip_later_failures(
    kind: type[s.AllExpression[str]] | type[s.AnyExpression[str]],
) -> None:
    decisive = kind is s.AnyExpression
    expression = kind((condition(None), condition(decisive), s.KeyReference()))
    assert s.evaluate(expression, NameTypeSystem()) == Success(decisive)


@pytest.mark.parametrize("kind", (s.AllExpression, s.AnyExpression))
def test_unknown_conditions_do_not_skip_reachable_failures(
    kind: type[s.AllExpression[str]] | type[s.AnyExpression[str]],
) -> None:
    expression = kind(
        (condition(None), s.KeyReference(), condition(kind is s.AnyExpression))
    )
    assert s.evaluate(expression, NameTypeSystem()) == Failure(
        s.UnboundKeySemanticError("Key requires MapFields")
    )


@pytest.mark.parametrize("kind", (s.EqualExpression, s.AssignableExpression))
def test_static_relations_distinguish_equal_spelling_in_different_scopes(
    kind: type[s.EqualExpression[str]] | type[s.AssignableExpression[str]],
) -> None:
    left = unknown()
    right = s.TypeValueReference(
        s.UnresolvedType("T", s.TypeSymbol(("models", "Other"), "T"))
    )
    assert s.evaluate(kind(left, left), NameTypeSystem()) == Success(True)
    assert s.evaluate(kind(left, right), NameTypeSystem()) == Success(
        s.IndeterminateCondition()
    )
    assert s.evaluate(kind(left, s.TypeReference("int")), NameTypeSystem()) == Success(
        s.IndeterminateCondition()
    )


@pytest.mark.parametrize("test", (s.TypeReference("int"), condition(True)))
def test_definite_earlier_case_skips_unknown_and_failing_outputs(
    test: s.Expression[str],
) -> None:
    expression = s.MapExpression(
        s.TypeReference("int"),
        (
            s.CaseExpression(test, s.TypeReference("float")),
            s.CaseExpression(condition(None), s.KeyReference()),
        ),
        s.KeyReference(),
    )
    assert s.evaluate(expression, NameTypeSystem()) == Success(s.ResolvedType("float"))


def test_two_uncertain_cases_preserve_order_and_default() -> None:
    expression = s.MapExpression(
        s.TypeReference("int"),
        (
            s.CaseExpression(condition(False), s.KeyReference()),
            s.CaseExpression(condition(None), s.TypeReference("str")),
            s.CaseExpression(
                s.EqualExpression(unknown("U"), s.TypeReference("int")),
                s.TypeReference("float"),
            ),
        ),
        s.TypeReference("bytes"),
    )
    assert s.evaluate(expression, NameTypeSystem()) == Success(
        s.IndeterminateType(
            s.ResolvedType("str | float | bytes"),
            (s.ResolvedType("str"), s.ResolvedType("float"), s.ResolvedType("bytes")),
        )
    )


def test_uncertain_case_without_default_retains_the_unmatched_alternative() -> None:
    expression = s.MapExpression(
        unknown(), (s.CaseExpression(s.TypeReference("int"), s.TypeReference("str")),)
    )
    assert s.evaluate(expression, NameTypeSystem()) == Success(
        s.IndeterminateType(
            s.ResolvedType("str"),
            (s.ResolvedType("str"), s.ResolvedType("Never")),
        )
    )


@pytest.mark.parametrize("same_symbol", (False, True))
def test_nested_map_predicates_preserve_uncertainty_only_when_selection_is_unknown(
    same_symbol: bool,
) -> None:
    nested = s.MapExpression(
        unknown(),
        (
            s.CaseExpression(
                unknown() if same_symbol else s.TypeReference("int"),
                s.TypeReference("int"),
            ),
        ),
        s.TypeReference("str"),
    )
    expression = s.MapExpression(
        s.TypeReference("int"),
        (
            s.CaseExpression(
                s.EqualExpression(nested, s.TypeReference("int")),
                s.TypeReference("bytes"),
            ),
        ),
        s.TypeReference("float"),
    )
    expected = (
        s.ResolvedType("bytes")
        if same_symbol
        else s.IndeterminateType(
            s.ResolvedType("bytes | float"),
            (s.ResolvedType("bytes"), s.ResolvedType("float")),
        )
    )
    assert s.evaluate(expression, NameTypeSystem()) == Success(expected)


def test_uncertain_case_composes_a_deferred_output() -> None:
    nested = s.MapExpression(
        s.InputReference(),
        (s.CaseExpression(s.TypeReference("int"), s.TypeReference("str")),),
        s.TypeReference("float"),
    )
    expression = s.MapExpression(
        unknown(),
        (s.CaseExpression(s.TypeReference("int"), nested),),
        s.TypeReference("bytes"),
    )
    result = s.evaluate(expression, NameTypeSystem()).unwrap()
    assert isinstance(result, s.IndeterminateType)
    assert result.possible_output == s.ResolvedType("str | float | bytes")


@pytest.mark.parametrize(
    ("subject", "pattern", "expected"),
    (
        (
            structure("list", unknown().value),
            s.ParameterizedTypePattern("list", (s.ExactTypePattern("int"),)),
            "str | bytes",
        ),
        (
            structure("list", unknown().value),
            s.ParameterizedTypePattern("list", (unknown(),)),
            "str",
        ),
        (
            structure("list", unknown().value),
            s.ParameterizedTypePattern("set", (s.ExactTypePattern("int"),)),
            "bytes",
        ),
        (
            structure("tuple", s.ResolvedType("int"), unknown().value),
            s.ParameterizedTypePattern(
                "tuple", (s.ExactTypePattern("str"), s.ExactTypePattern("int"))
            ),
            "bytes",
        ),
        (
            structure("tuple", unknown().value, s.ResolvedType("int")),
            s.ParameterizedTypePattern(
                "tuple", (s.ExactTypePattern("str"), s.ExactTypePattern("bytes"))
            ),
            "bytes",
        ),
        (
            structure("list", unknown().value),
            s.ParameterizedTypePattern(
                "list", (s.ExactTypePattern("int"), s.ExactTypePattern("int"))
            ),
            "bytes",
        ),
    ),
)
def test_structural_cases_preserve_known_and_unknown_positions(
    subject: s.TypeValue[str], pattern: s.TypePattern[str], expected: str
) -> None:
    expression = s.MapExpression(
        s.TypeValueReference(subject),
        (s.CaseExpression(pattern, s.TypeReference("str")),),
        s.TypeReference("bytes"),
    )
    result = s.evaluate(expression, NameTypeSystem()).unwrap()
    if " | " in expected:
        assert isinstance(result, s.IndeterminateType)
        assert result.possible_output == s.ResolvedType(expected)
    else:
        assert result == s.ResolvedType(expected)


def test_unresolved_pattern_can_match_a_known_subject() -> None:
    expression = s.MapExpression(
        s.TypeReference("list[int]"),
        (
            s.CaseExpression(
                s.ParameterizedTypePattern("list", (unknown(),)), s.TypeReference("str")
            ),
        ),
        s.TypeReference("bytes"),
    )
    adapter = NameTypeSystem(
        parameterized_types=(("list[int]", s.ParameterizedTypeShape("list", ("int",))),)
    )
    result = s.evaluate(expression, adapter).unwrap()
    assert isinstance(result, s.IndeterminateType)
    assert result.possible_output == s.ResolvedType("str | bytes")


@pytest.mark.parametrize("reverse", (False, True))
def test_repeated_capture_narrows_to_its_known_argument(reverse: bool) -> None:
    arguments = (
        (unknown().value, s.ResolvedType("int"))
        if reverse
        else (s.ResolvedType("int"), unknown().value)
    )
    expression = s.MapExpression(
        s.TypeValueReference(structure("tuple", *arguments)),
        (
            s.CaseExpression(
                s.ParameterizedTypePattern("tuple", (ITEM, ITEM)),
                ITEM,
            ),
        ),
        s.TypeReference("bytes"),
    )
    assert s.evaluate(expression, NameTypeSystem()) == Success(
        s.IndeterminateType(
            s.ResolvedType("int | bytes"),
            (s.ResolvedType("int"), s.ResolvedType("bytes")),
        )
    )


def test_same_symbol_repeated_capture_remains_definite() -> None:
    expression = s.MapExpression(
        s.TypeValueReference(structure("tuple", unknown().value, unknown().value)),
        (
            s.CaseExpression(
                s.ParameterizedTypePattern("tuple", (ITEM, ITEM)),
                ITEM,
            ),
        ),
        s.KeyReference(),
    )
    assert s.evaluate(expression, NameTypeSystem()) == Success(unknown().value)


def test_known_capture_mismatch_survives_a_later_unknown() -> None:
    expression = s.MapExpression(
        s.TypeValueReference(
            structure(
                "tuple", s.ResolvedType("int"), s.ResolvedType("str"), unknown().value
            )
        ),
        (
            s.CaseExpression(
                s.ParameterizedTypePattern("tuple", (ITEM,) * 3),
                s.KeyReference(),
            ),
        ),
        s.TypeReference("bytes"),
    )
    assert s.evaluate(expression, NameTypeSystem()) == Success(s.ResolvedType("bytes"))


def test_nested_capture_reconciliation_combines_known_positions() -> None:
    left = structure("tuple", unknown().value, s.ResolvedType("int"))
    right = structure("tuple", s.ResolvedType("str"), unknown("U").value)
    expression = s.MapExpression(
        s.TypeValueReference(structure("tuple", left, right)),
        (
            s.CaseExpression(
                s.ParameterizedTypePattern("tuple", (ITEM, ITEM)),
                ITEM,
            ),
        ),
        s.TypeReference("bytes"),
    )
    result = s.evaluate(expression, BuildingTypeSystem()).unwrap()
    assert isinstance(result, s.IndeterminateType)
    assert result.alternatives[0] == s.ResolvedType("tuple[str, int]")


def test_captured_union_templates_keep_static_provenance() -> None:
    expression = s.MapExpression(
        s.TypeValueReference(structure("list", unknown().value)),
        (
            s.CaseExpression(
                s.ParameterizedTypePattern("list", (ITEM,)),
                s.ParameterizedTypeTemplate(
                    "tuple",
                    (s.UnionExpression((ITEM, s.TypeReference("None"))),),
                ),
            ),
        ),
    )
    result = s.evaluate(expression, BuildingTypeSystem()).unwrap()
    assert isinstance(result, s.UnresolvedType)
    assert isinstance(result.provenance, s.ParameterizedTypeShape)
    argument = result.provenance.arguments[0]
    assert isinstance(argument, s.UnresolvedType)
    assert isinstance(argument.provenance, s.UnionTypeShape)
    assert argument.provenance.members == (unknown().value, s.ResolvedType("None"))
    assert s.evaluate(
        s.EqualExpression(expression, expression), BuildingTypeSystem()
    ) == Success(True)


def test_reachable_non_type_output_fails_before_evaluating_the_remainder() -> None:
    expression = s.MapExpression(
        unknown(),
        (s.CaseExpression(s.TypeReference("int"), s.FieldName("invalid")),),
        s.KeyReference(),
    )
    assert s.evaluate(expression, NameTypeSystem()) == Failure(
        s.ExpectedTypeSemanticError("indeterminate Map outputs must evaluate to types")
    )


def test_union_non_type_member_fails_before_evaluating_later_members() -> None:
    expression = s.UnionExpression[str]((s.FieldName("invalid"), s.KeyReference()))
    assert s.evaluate(expression, NameTypeSystem()) == Failure(
        s.ExpectedTypeSemanticError("union members must evaluate to types")
    )


def test_uncertain_output_union_failure_preserves_adapter_error_identity() -> None:
    issue = s.SemanticAdapterError("union unavailable")
    expression = s.MapExpression(
        unknown(),
        (s.CaseExpression(s.TypeReference("int"), s.TypeReference("str")),),
        s.TypeReference("bytes"),
    )
    result = s.evaluate(
        expression, FailureInjectionTypeSystemProxy(NameTypeSystem(), "union", issue)
    )
    assert isinstance(result, Failure)
    assert result.failure() is issue


@pytest.mark.parametrize("case", (s.TypeReference("int"), unknown("U")))
def test_unresolved_exact_cases_keep_the_default_reachable(
    case: s.Expression[str],
) -> None:
    expression = s.MapExpression(
        unknown(),
        (s.CaseExpression(case, s.TypeReference("str")),),
        s.TypeReference("bytes"),
    )
    result = s.evaluate(expression, NameTypeSystem()).unwrap()
    assert isinstance(result, s.IndeterminateType)
    assert result.possible_output == s.ResolvedType("str | bytes")


def test_empty_logical_conditions_keep_their_identities() -> None:
    assert s.evaluate(s.AllExpression[str](()), NameTypeSystem()) == Success(True)
    assert s.evaluate(s.AnyExpression[str](()), NameTypeSystem()) == Success(False)


@pytest.mark.parametrize("kind", (s.EqualExpression, s.AssignableExpression))
def test_nested_indeterminate_operands_are_not_their_union_bound(
    kind: type[s.EqualExpression[str]] | type[s.AssignableExpression[str]],
) -> None:
    nested = s.MapExpression(
        unknown(),
        (s.CaseExpression(s.TypeReference("int"), s.TypeReference("int")),),
        s.TypeReference("str"),
    )
    assert s.evaluate(
        kind(nested, s.TypeReference("int")), NameTypeSystem()
    ) == Success(s.IndeterminateCondition())
    assert s.evaluate(
        kind(nested, s.TypeReference("bytes")), NameTypeSystem()
    ) == Success(False)


def test_unresolved_union_identity_is_independent_of_member_order() -> None:
    left = s.UnionExpression((unknown(), s.TypeReference("int")))
    right = s.UnionExpression((s.TypeReference("int"), unknown()))
    assert s.evaluate(s.EqualExpression(left, right), NameTypeSystem()) == Success(True)
    assert s.evaluate(
        s.EqualExpression(left, s.TypeReference("int")), NameTypeSystem()
    ) == Success(s.IndeterminateCondition())
    assert s.evaluate(
        s.EqualExpression(left, s.TypeReference("str")), NameTypeSystem()
    ) == Success(False)


def test_unresolved_union_subjects_retain_selection_provenance() -> None:
    expression = s.MapExpression(
        s.UnionExpression((unknown(), s.TypeReference("int"))),
        (s.CaseExpression(s.TypeReference("int"), s.TypeReference("str")),),
        s.TypeReference("bytes"),
    )
    assert s.evaluate(
        s.EqualExpression(expression, s.TypeReference("str")), NameTypeSystem()
    ) == Success(s.IndeterminateCondition())


@pytest.mark.parametrize(
    ("expression", "operation"),
    (
        (
            s.EqualExpression(
                s.TypeValueReference(structure("list", unknown().value)),
                s.TypeValueReference(structure("list", unknown().value)),
            ),
            "equal",
        ),
        (
            s.AssignableExpression(
                s.MapExpression(
                    unknown(),
                    (s.CaseExpression(s.TypeReference("int"), s.TypeReference("int")),),
                    s.TypeReference("str"),
                ),
                s.TypeReference("int"),
            ),
            "assignable",
        ),
        (
            s.MapExpression(
                s.TypeReference("list[int]"),
                (
                    s.CaseExpression(
                        s.ParameterizedTypePattern("list", (unknown(),)),
                        s.TypeReference("str"),
                    ),
                ),
                s.TypeReference("bytes"),
            ),
            "inspect",
        ),
        (s.ParameterizedTypeTemplate("list", (unknown(),)), "build"),
    ),
)
def test_uncertainty_preserves_backend_failure_identity(
    expression: s.Expression[str], operation: AdapterOperation
) -> None:
    issue = s.SemanticAdapterError("operation unavailable")
    result = s.evaluate(
        expression, FailureInjectionTypeSystemProxy(NameTypeSystem(), operation, issue)
    )
    assert isinstance(result, Failure)
    assert result.failure() is issue


def test_opaque_parameter_cannot_capture_unknown_type_arguments() -> None:
    expression = s.MapExpression(
        unknown(),
        (
            s.CaseExpression(
                s.ParameterizedTypePattern("list", (ITEM,)),
                ITEM,
            ),
        ),
        s.TypeReference("bytes"),
    )
    assert s.evaluate(
        expression,
        NameTypeSystem(),
        s.EvaluationContext(value=s.ResolvedType("unrelated")),
    ) == Failure(
        s.UnresolvedCaptureSemanticError(
            "cannot capture type arguments from an unresolved type parameter"
        )
    )


def test_opaque_parameter_supports_a_structural_case_without_capture() -> None:
    expression = s.MapExpression(
        unknown(),
        (
            s.CaseExpression(
                s.ParameterizedTypePattern("list", (s.ExactTypePattern("int"),)),
                s.TypeReference("str"),
            ),
        ),
        s.TypeReference("bytes"),
    )
    result = s.evaluate(expression, NameTypeSystem()).unwrap()
    assert isinstance(result, s.IndeterminateType)
    assert result.possible_output == s.ResolvedType("str | bytes")


def test_parameterized_arguments_accept_nested_deferred_maps() -> None:
    expression = s.ParameterizedTypeTemplate(
        "tuple",
        (
            s.MapExpression(
                s.InputReference(),
                (s.CaseExpression(s.TypeReference("int"), s.TypeReference("str")),),
            ),
        ),
    )

    assert s.evaluate(expression, BuildingTypeSystem()) == Success(
        s.ResolvedType("tuple[str]")
    )


def test_non_type_parameterized_argument_stops_before_later_unbound_input() -> None:
    expression = s.ParameterizedTypeTemplate(
        "tuple", (condition(True), s.InputReference())
    )

    assert s.evaluate(expression, BuildingTypeSystem()) == Failure(
        s.ExpectedTypeSemanticError(
            "parameterized type arguments must evaluate to types"
        )
    )
