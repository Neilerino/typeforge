from typeforge.compiler.source import (
    RawTypeExpression,
    parse_source,
)


def test_missing_annotation_is_distinct_from_authored_none() -> None:
    module = (
        parse_source(
            "def unannotated(value): ...\n"
            "def annotated(value: None) -> None: ...\n"
            "type Nothing = None\n"
        )
        .unwrap()
        .source
    )
    unannotated, annotated = module.functions
    assert unannotated.parameters[0].annotation is None
    assert unannotated.returns is None
    assert isinstance(annotated.parameters[0].annotation, RawTypeExpression)
    assert isinstance(annotated.returns, RawTypeExpression)
    assert isinstance(module.aliases[0].value, RawTypeExpression)
    assert annotated.returns.source == module.aliases[0].value.source == "None"
