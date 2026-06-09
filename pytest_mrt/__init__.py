from .config import MRTConfig
from .django_testcase import MRTTestCase

try:
    from importlib.metadata import version

    __version__ = version("pytest-mrt")
except Exception:
    __version__ = "0.0.0"

__all__ = ["MRTConfig", "MRTTestCase"]
