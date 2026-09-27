from importlib.metadata import PackageNotFoundError, version
from typing import TYPE_CHECKING, Any

from .config import MRTConfig as MRTConfig

if TYPE_CHECKING:
    from .django_testcase import MRTTestCase as MRTTestCase

try:
    __version__ = version("pytest-mrt")
except PackageNotFoundError:  # running from a source tree without an install
    __version__ = "0.0.0"

__all__ = ["MRTConfig", "MRTTestCase", "__version__"]


def __getattr__(name: str) -> Any:
    """Load MRTTestCase on first use (PEP 562).

    Importing it eagerly pulled SchemaSnapshot, SmartSeeder and SQLAlchemy into
    every `import pytest_mrt` — measured at 193ms of the CLI's 262ms startup,
    for a class only unittest-based Django projects touch.
    """
    if name == "MRTTestCase":
        from .django_testcase import MRTTestCase

        return MRTTestCase
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
