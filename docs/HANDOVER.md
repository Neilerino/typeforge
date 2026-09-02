# Typeforge compiler cutover handoff

## Next-session focus

Complete the compiler cutover to shared parameterized-type and deferred Input semantics. Start from the strict compiler contract tests; preserve the existing generated-stub behavior; delete the duplicate compiler matching path only after the shared path is active.

## Repository state

- Worktree is clean at e543a82 (Added seam to the compiler module for proper parameterization handling).
- Shared structural matching and deferred Map creation are complete.
- Full validation last run: 333 passed, 6 xfailed. Five xfails are the compiler migration contracts; the sixth is the pre-existing stubpy xfail.
- ruff check ., ruff format --check ., mypy src, and pyright src passed.

## Read first

- Overall design: docs/ideas/pydantic-integration-redesign.md
- Completed semantics task and deferred resumption decision: docs/in_progress_tasks/deferred-input-map-semantics.md
- Compiler contracts: tests/unit/compiler/test_type_system.py and tests/unit/compiler/test_semantic_lowering.py
- Public generated-output contract: tests/unit/compiler/test_pipeline.py, test_schema_boundaries_resolve_in_model_fields_and_generated_stubs
- Shared interfaces: src/typeforge/semantics/protocols.py, src/typeforge/semantics/domain/models.py, and src/typeforge/semantics/map_evaluation.py

## Completed compiler scaffolding

- src/typeforge/compiler/records.py defines ParameterizedType and includes it in StaticType and is_static().
- src/typeforge/compiler/_pipeline_records.py converts ParameterizedType back to emitted TypeApplication.
- CompilerTypeSystem.inspect() and build() exist but raise NotImplementedError.
- Contract tests use keyword arguments for AppliedTypeExpression and short docstrings showing authored Python syntax.

## Remaining slices

### 1. Compiler type-system adapter

Implement CompilerTypeSystem.inspect() and build() for ParameterizedType and ParameterizedTypeShape. Remove the two strict xfails in tests/unit/compiler/test_type_system.py only when each operation passes.

Completion: compiler parameterized types round-trip through the production TypeSystem adapter, and modeled failures still cross the semantics seam unchanged.

### 2. Concrete parameterized-type lowering

Change compiler semantic lowering so an ordinary AppliedTypeExpression, such as list[int], becomes TypeReference(ParameterizedType(...)) instead of an opaque NamedType containing list[int]. Preserve the existing string-Literal field-name special case.

Completion: test_parameterized_type_lowers_to_a_structured_compiler_type passes without its xfail.

### 3. Role-specific Map lowering

Lower a parameterized Case test to ParameterizedTypePattern and a parameterized Case output to ParameterizedTypeTemplate. Value in a structural pattern becomes CaptureValuePattern; Value in an output remains ValueReference. Prefer explicit helpers for concrete types, case tests, and output templates over hidden positional inference.

Completion: test_map_lowers_parameterized_case_roles_to_shared_semantics passes without its xfail.

### 4. Compiler Input lowering

Lower RuntimeInputTypeExpression to InputReference. Evaluate the resulting shared MapExpression to DeferredMap, and consume DeferredMap.possible_output for static compiler output.

Completion: test_input_map_lowers_and_evaluates_to_a_deferred_map passes without its xfail.

### 5. Pipeline cutover and deletion

Route structural Map and Input static output through shared semantics. Keep the existing pipeline contract green, including Case[list[Value], set[Value]] to set[int]. Then remove the duplicate compiler behavior in src/typeforge/compiler/_pipeline_adaptation.py, including _match_schema_pattern, _substitute_schema_capture, and the direct RuntimeInputType output-union path when they have no callers.

Completion: all five compiler migration xfails are removed, the public pipeline behavior is unchanged, and no second structural matcher or deferred-output calculation remains in the compiler.

## Working conventions established in this thread

- Keep semantics responsible for Typeforge meaning; compiler code owns source adaptation and standard typing emission.
- TypeSystem.inspect() and build() only inspect and construct parameterized backend types. They do not know about Map, Case, or Value.
- Use keyword arguments when constructing source-model dataclasses such as AppliedTypeExpression.
- Keep contract-test docstrings short and show the corresponding authored Python type expression.
- Work vertically: run one strict xfail with --runxfail, implement the minimum behavior, then remove that xfail.

## Suggested skills

- tdd — drive each remaining strict xfail from red to green as a separate vertical slice.
- codebase-design — check seam placement if lowering begins to mix compiler representation with shared semantics.
- code-review — review the final cutover and deletion against project standards and this handoff before finishing.
