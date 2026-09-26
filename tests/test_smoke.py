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


@pytest.mark.parametrize("lang", ["de-de", "en-us", "fr-fr", "da-dk"])
def test_initialize_loads_on_any_device_language(skill, monkeypatch, lang):
    """A HiveMind hub runs one ovos-core for users in several languages,
    so the device's own language cannot decide whether this provider is
    there at all - it always loads, and each search's language decides
    whether it answers (see test_request_language.py)."""
    monkeypatch.setattr(BechsteinTales, "lang", lang, raising=False)
    skill._load_index = MagicMock(return_value={"Aschenbrödel": {}})
    skill.add_event = MagicMock()

    skill.initialize()

    skill._load_index.assert_called_once()
    assert skill.add_event.call_count == 3
    assert skill.index == {"Aschenbrödel": {}}
    logged = " ".join(str(c) for c in skill.log.info.call_args_list)
    assert "German" in logged and "de-*" in logged
