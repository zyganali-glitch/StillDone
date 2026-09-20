"""Minimal bootstrap smoke test to verify packaging and environment."""

import stilldone


def test_package_metadata() -> None:
    """Verify package version and presence."""
    assert stilldone.__version__ == "0.1.0"
