"""Shared pytest fixtures for the bechstein-tales skill test suite."""
import importlib.util
from pathlib import Path
from unittest.mock import MagicMock

import pytest

_INIT_PATH = Path(__file__).resolve().parents[1] / "__init__.py"
_spec = importlib.util.spec_from_file_location("bechstein_tales_skill", _INIT_PATH)
_module = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_module)

BechsteinTales = _module.BechsteinTales
StoryFetchError = _module.StoryFetchError
COMMON_READING_SEARCH_RESPONSE = _module.COMMON_READING_SEARCH_RESPONSE
COMMON_READING_FETCH_CONTENT_RESPONSE = _module.COMMON_READING_FETCH_CONTENT_RESPONSE


@pytest.fixture
def skill(monkeypatch):
    s = BechsteinTales.__new__(BechsteinTales)
    s.log = MagicMock()
    s.skill_id = "ovos-skill-bechstein-tales.test"
    s.status = MagicMock()
    s._bus = MagicMock()
    s._settings = {}
    monkeypatch.setattr(BechsteinTales, "lang", "de-de", raising=False)
    s._book_soup_cache = {}
    s.index = {}
    return s
