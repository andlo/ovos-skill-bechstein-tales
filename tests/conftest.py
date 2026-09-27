"""Shared pytest fixtures for the bechstein-tales skill test suite."""
import importlib.util
from pathlib import Path
from unittest.mock import MagicMock

import pytest
import requests

_INIT_PATH = Path(__file__).resolve().parents[1] / "__init__.py"
_spec = importlib.util.spec_from_file_location("bechstein_tales_skill", _INIT_PATH)
_module = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_module)

BechsteinTales = _module.BechsteinTales
StoryFetchError = _module.StoryFetchError
COMMON_READING_SEARCH_RESPONSE = _module.COMMON_READING_SEARCH_RESPONSE
COMMON_READING_FETCH_CONTENT_RESPONSE = _module.COMMON_READING_FETCH_CONTENT_RESPONSE
COMMON_READING_PONG = _module.COMMON_READING_PONG
normalize_title = _module.normalize_title
title_aliases = _module.title_aliases
StoryCache = _module.StoryCache
extract_book = _module.extract_book
skill_module = _module

# real pages from gutenberg.org, cut down to what the tests need
FIXTURES = Path(__file__).resolve().parent / "fixtures"


def fixture_page(name):
    return (FIXTURES / name).read_bytes()


class FakeGutenberg:
    """Stands in for requests.get: answers each URL from `pages` (a
    requests.Response, an exception to raise, or a callable returning
    either) and records every request."""

    def __init__(self, pages):
        self.pages = pages
        self.requests = []

    def get(self, url, headers=None, timeout=None):
        self.requests.append({"url": url, "headers": dict(headers or {}), "timeout": timeout})
        page = self.pages[url]
        if callable(page) and not isinstance(page, requests.Response):
            page = page(headers or {})
        if isinstance(page, Exception):
            raise page
        return page


def response(content=b"", status=200, last_modified=None):
    r = requests.Response()
    r.status_code = status
    r._content = content
    r.url = "https://www.gutenberg.org/test"
    r.reason = "Not Found" if status == 404 else "OK"
    if last_modified:
        r.headers["Last-Modified"] = last_modified
    return r


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    """No test reaches gutenberg.org: one that does not answer the request
    itself (see FakeGutenberg) fails."""
    def refuse(url, *args, **kwargs):
        raise AssertionError(f"a test tried to fetch {url}")
    monkeypatch.setattr(requests, "get", refuse)


@pytest.fixture
def gutenberg(monkeypatch):
    """A FakeGutenberg in place of requests.get: fill in its `pages`."""
    fake = FakeGutenberg({})
    monkeypatch.setattr(requests, "get", fake.get)
    return fake


@pytest.fixture
def skill(monkeypatch, tmp_path):
    s = BechsteinTales.__new__(BechsteinTales)
    s.log = MagicMock()
    s.skill_id = "ovos-skill-bechstein-tales.test"
    s.status = MagicMock()
    s._bus = MagicMock()
    s._settings = {}
    monkeypatch.setattr(BechsteinTales, "lang", "de-de", raising=False)
    s.served = {"de"}
    s._init_story_cache(str(tmp_path / "story-cache"))
    s.index = {}
    return s
