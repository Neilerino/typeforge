CHECK_PATHS := $(filter-out check,$(MAKECMDGOALS))

.PHONY: check

check:
	@uv run --quiet python scripts/check.py $(CHECK_PATHS)

ifneq ($(strip $(CHECK_PATHS)),)
.PHONY: $(CHECK_PATHS)
$(CHECK_PATHS):
	@:
endif
