"""The installed package metadata matches the code."""

from __future__ import annotations

from importlib.metadata import version

import bursakit


def test_version_matches_the_installed_metadata() -> None:
    assert version("bursakit") == bursakit.__version__
