import re
import sys
from pathlib import Path

SOURCE_PATH = (Path(__file__).parents[2] / "src").resolve()
SOURCE_ROOT = str(SOURCE_PATH)


STDLIB_MODULES = "|".join(
    re.escape(module) for module in sorted(sys.stdlib_module_names)
)
STDLIB_DEPENDENCY = re.compile(rf"^(?:{STDLIB_MODULES})(?:\..*)?$")
