# Specification-Based Testing Resources

## Knowledge

- [Book: _Specification by Example_ — Gojko Adzic](https://www.manning.com/books/specification-by-example)
  The foundational practitioner study of collaborative specifications, concrete examples, automated validation, and living documentation. Use for the broader method and its organizational patterns.
- [Guide: “Behaviour-Driven Development” — Cucumber](https://cucumber.io/docs/bdd/)
  A concise primary guide to discovery, formulation, and automation. Use for turning conversations and examples into implementation-driving executable specifications.
- [Essay: “Specification By Example” — Martin Fowler](https://martinfowler.com/bliki/SpecificationByExample.html)
  Explains why examples are powerful but necessarily incomplete. Use when deciding what examples can specify and where rules or properties must supplement them.
- [Essay: “Test Driven Development” — Martin Fowler](https://martinfowler.com/bliki/TestDrivenDevelopment.html)
  A compact account of test lists, red–green–refactor, and the design pressure created by testing interfaces first. Use for sequencing implementation after the specification is agreed.
- [pytest guide: “How to use skip and xfail”](https://docs.pytest.org/en/stable/how-to/skipping.html)
  Authoritative behavior for `xfail`, `strict=True`, `raises`, `--runxfail`, XPASS, and parametrized cases. Use whenever expected failures enter the workflow.
- [Typeforge design principles](DESIGN.md)
  The repository's authority for public semantics and architectural constraints. Use to derive rules before writing examples.
- [Typeforge's completed migration specification](tests/unit/semantics/test_migration_spec.py)
  A local example where strict expected failures became ordinary regression specifications after implementation shipped.
- [Hypothesis tutorial: “When to use property-based testing”](https://hypothesis.readthedocs.io/en/latest/tutorial/introduction.html#when-to-use-hypothesis-and-property-based-testing)
  Shows how general properties complement hand-picked examples. Use later for invariants such as deterministic compilation and compiler non-crashing guarantees.

## Wisdom (Communities)

- [pytest GitHub Discussions](https://github.com/pytest-dev/pytest/discussions)
  Maintainer-visible forum for validating nuanced marker behavior and test-suite conventions.
- [Cucumber Community](https://cucumber.io/community/)
  Practitioner community centered on discovery, example formulation, and executable specifications across languages and tools.
