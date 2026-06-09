from .config import MRTConfig

try:
    from .django_testcase import MRTTestCase

    _TESTCASE_AVAILABLE = True
except ImportError:
    _TESTCASE_AVAILABLE = False

try:
    from importlib.metadata import version

    __version__ = version("pytest-mrt")
except Exception:
    __version__ = "0.0.0"

__all__ = ["MRTConfig", "MRTTestCase"] if _TESTCASE_AVAILABLE else ["MRTConfig"]
