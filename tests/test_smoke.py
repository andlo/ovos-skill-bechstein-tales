"""Smoke tests + loading on every device language."""
from unittest.mock import MagicMock

import pytest

from conftest import BechsteinTales, StoryFetchError


def test_imports_cleanly():
    assert BechsteinTales is not None
    assert issubclass(StoryFetchError, Exception)


def test_is_an_ovos_skill():
    from ovos_workshop.skills import OVOSSkill
    assert issubclass(BechsteinTales, OVOSSkill)


def test_load_index_uses_bundled_de_de(skill):
    index = skill._load_index()
    assert len(index) > 50
    assert "Aschenbrödel" in index
