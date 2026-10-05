# 09 — Record and Fields construction

Authors write a reusable TypedDict transform with a lexical field binding:

```python
@type_function
def Public[T]():
    return Record(
        Map[field.name, Literal["password"]: Drop, ...: field]
        for field in Fields[T]
    )
```

The transform removes password and preserves the complete remaining fields,
including requiredness, readonly state, and runtime metadata. Imports, source
validation, specialization, and all three checker witnesses are covered by
[the production contract](https://github.com/Neilerino/typeforge/blob/54f79352abc6b25cd6eef0949be1168eb4e2772a/tests/unit/test_record_fields_contract.py).

Download [architecture.html](architecture.html) and open it locally for the
interactive C4 code diagram. Its source badges link to the exact implementation
revision. The [light screenshot](architecture.visual-check.1440x900.light.png)
provides a GitHub preview.

The left path constructs a symbolic runtime template once, then lowers its typing
arguments at Schema. The right path parses the supported source comprehension
without execution. Both produce scoped RecordExpression data. The shared
Evaluator binds each original RecordField and emits either that field or Drop.
Existing family adapters, record materialization, and Pydantic emission retain
their responsibilities.

Review the source parser's single unfiltered Fields iteration, declaration-scoped
field identity, context reset after construction failure, original type-parameter
visibility after all-Drop, and passthrough flags/metadata. MapFields and ambient
Key/Value are removed, including repository consumers and unused IR helpers.

The compiler retains named generic aliases with one parameter over visible
TypedDict declarations. Runtime Schema supports concrete inline records and
generic-model specialization/rebuilds. Field construction and immutable edits
arrive in slice 10; local aliases in 11; field and record unions in 12–13.
Future Protocol output remains a separate record-family adapter decision.

Validation: all six repository checks pass, with 1,458 tests passing and no xfails.
The [delivery receipt](delivery-receipt.json) proves 9/9 showcase checks, zero
composition errors or warnings, and pinned source evidence. The
[browser receipt](architecture.visual-check.json) proves containment at all four
desktop sizes. The [separate review record](review.json) reports actual inspection
of the four endpoint screenshots in light and dark themes.
