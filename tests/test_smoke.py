"""Smoke tests + the load-time language gate in initialize()."""
from unittest.mock import MagicMock

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


def test_initialize_stays_inert_for_non_german_device(skill, monkeypatch):
    monkeypatch.setattr(BechsteinTales, "lang", "en-us", raising=False)
    skill._load_index = MagicMock()
    skill.add_event = MagicMock()

    skill.initialize()

    skill._load_index.assert_not_called()
    skill.add_event.assert_not_called()
    assert skill.index == {}


def test_initialize_loads_normally_for_german_device(skill, monkeypatch):
    monkeypatch.setattr(BechsteinTales, "lang", "de-de", raising=False)
    skill._load_index = MagicMock(return_value={"Aschenbrödel": {}})
    skill.add_event = MagicMock()

    skill.initialize()

    skill._load_index.assert_called_once()
    assert skill.add_event.call_count == 2
    assert skill.index == {"Aschenbrödel": {}}
