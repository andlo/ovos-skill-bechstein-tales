"""Tests for get_story_paragraphs() - includes a regression case for a
real bug found while building this: get_text(' ', strip=True) inserts a
spurious space at drop-cap span boundaries ('<span>E</span>s war einmal'
-> 'E s war einmal'), and the source HTML's line-wrapped text nodes
contain literal newlines that need collapsing."""
from unittest.mock import MagicMock

import pytest
import requests
from conftest import StoryFetchError

SAMPLE_HTML = """
<html><body>
<div class='chapter' id='chap_1'>
<h2 class='nobreak'>Aschenbrödel.</h2>
<p class='drop_w'><span class='drop'>E</span>s war einmal ein Mann und
eine Frau, die hatten
zwei Töchter.</p>
<p>Und die Stieftochter war fromm und gut.</p>
</div>
<div class='chapter' id='chap_2'>
<h2 class='nobreak'>Das Dornröschen.</h2>
<p>Es waren vor Zeiten ein König und eine Königin.</p>
</div>
</body></html>
"""


def test_get_story_paragraphs_fixes_dropcap_and_linewrap(skill, monkeypatch):
    fake_response = MagicMock(text=SAMPLE_HTML)
    fake_response.raise_for_status = MagicMock()
    monkeypatch.setattr(requests, "get", lambda *a, **kw: fake_response)

    paragraphs = skill.get_story_paragraphs({"url": "http://x/book", "anchor": "chap_1"})

    assert paragraphs[0] == "Es war einmal ein Mann und eine Frau, die hatten zwei Töchter."
    assert paragraphs[1] == "Und die Stieftochter war fromm und gut."


def test_get_story_paragraphs_scoped_to_correct_chapter_div(skill, monkeypatch):
    fake_response = MagicMock(text=SAMPLE_HTML)
    fake_response.raise_for_status = MagicMock()
    monkeypatch.setattr(requests, "get", lambda *a, **kw: fake_response)

    paragraphs = skill.get_story_paragraphs({"url": "http://x/book", "anchor": "chap_2"})

    assert paragraphs == ["Es waren vor Zeiten ein König und eine Königin."]


def test_get_story_paragraphs_missing_anchor_raises(skill, monkeypatch):
    fake_response = MagicMock(text=SAMPLE_HTML)
    fake_response.raise_for_status = MagicMock()
    monkeypatch.setattr(requests, "get", lambda *a, **kw: fake_response)

    with pytest.raises(StoryFetchError):
        skill.get_story_paragraphs({"url": "http://x/book", "anchor": "chap_999"})


def test_get_book_soup_caches_and_wraps_request_exception(skill, monkeypatch):
    calls = []

    def fake_get(url, timeout):
        calls.append(url)
        return MagicMock(text=SAMPLE_HTML, raise_for_status=MagicMock())

    monkeypatch.setattr(requests, "get", fake_get)
    skill._get_book_soup("http://x/book")
    skill._get_book_soup("http://x/book")
    assert len(calls) == 1  # cached on second call

    def fail(*a, **kw):
        raise requests.ConnectionError("boom")
    monkeypatch.setattr(requests, "get", fail)
    with pytest.raises(StoryFetchError):
        skill._get_book_soup("http://x/other-book")
