# Typeforge Development Guidelines

## Design

* Keep data separate from behavior.
* Represent domain data with frozen, slotted dataclasses.
* Prefer functions consuming data or protocols over stateful service classes.
* Keep the runtime marker layer dependency-free and inert.
* Keep third-party frontend models behind Typeforge-owned protocols and data models.

## Typing and failures

* Use strict static typing throughout the project.
* Represent expected failures as typed return values.
* Reserve exceptions for unexpected failures and deliberate API boundaries.
* Avoid casts and `Any` unless an integration boundary makes them unavoidable.

## Style

* Prefer clear names and small functions over explanatory comments.
* Add comments only when intent cannot be expressed through structure or naming.
* Prefer immutable transformations over in-place mutation.
