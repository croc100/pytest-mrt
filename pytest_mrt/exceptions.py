"""
Custom exceptions for pytest-mrt.

Core logic raises these; framework layers (pytest fixture, CLI) catch and
convert them to framework-appropriate errors (pytest.fail, typer.Exit).
"""


class MRTException(Exception):
    """Base exception for all MRT errors."""


class MRTConfigError(MRTException):
    """Configuration validation error (missing file, invalid path, etc.)."""
