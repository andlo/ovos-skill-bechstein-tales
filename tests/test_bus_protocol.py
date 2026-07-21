"""Tests for the ovos.common_reading.* bus protocol handlers."""
from unittest.mock import MagicMock

from conftest import COMMON_READING_SEARCH_RESPONSE, COMMON_READING_FETCH_CONTENT_RESPONSE, StoryFetchError


def make_message(data=None):
    m = MagicMock()
    m.data = data or {}
    m.reply = MagicMock(side_effect=lambda mtype, d: MagicMock(msg_type=mtype, data=d))
    return m


def _sample_index():
    return {
        "Aschenbrödel": {"url": "http://x/book", "anchor": "chap_1"},
        "Das Dornröschen": {"url": "http://x/book", "anchor": "chap_2"},
    }


def test_handle_search_matches_by_phrase(skill):
    skill.index = _sample_index()

    skill.handle_search(make_message({"phrase": "aschenbrödel"}))

    sent = skill.bus.emit.call_args[0][0]
    assert sent.msg_type == COMMON_READING_SEARCH_RESPONSE
    assert sent.data["title"] == "Aschenbrödel"
    assert sent.data["content_id"] == "Aschenbrödel"
    assert sent.data["author"] == "Ludwig Bechstein"
    assert sent.data["source"] == "Project Gutenberg"


def test_handle_search_stays_silent_on_empty_index(skill):
    skill.index = {}
    skill.handle_search(make_message({"phrase": "anything"}))
    skill.bus.emit.assert_not_called()


def test_handle_search_stays_silent_when_collection_hint_does_not_match(skill):
    skill.index = _sample_index()
    skill.handle_search(make_message({"phrase": "aschenbrödel", "collection_hint": "grimm"}))
    skill.bus.emit.assert_not_called()


def test_handle_search_responds_when_collection_hint_matches(skill):
    skill.index = _sample_index()
    skill.handle_search(make_message({"phrase": "aschenbrödel", "collection_hint": "bechstein"}))
    skill.bus.emit.assert_called_once()


def test_handle_search_surprise_me_with_matching_hint_and_no_phrase(skill):
    skill.index = _sample_index()
    skill.handle_search(make_message({"phrase": None, "collection_hint": "ludwig bechstein"}))
    skill.bus.emit.assert_called_once()
    data = skill.bus.emit.call_args[0][0].data
    assert data["title"] in skill.index


def test_handle_search_no_phrase_no_hint_stays_silent(skill):
    skill.index = _sample_index()
    skill.handle_search(make_message({"phrase": None, "collection_hint": None}))
    skill.bus.emit.assert_not_called()


def test_handle_search_stays_silent_for_mismatched_content_type(skill):
    skill.index = _sample_index()
    skill.handle_search(make_message({"phrase": "aschenbrödel", "content_type": "article"}))
    skill.bus.emit.assert_not_called()


def test_handle_search_responds_for_matching_content_type(skill):
    skill.index = _sample_index()
    for content_type in ["story", "tale", "STORY"]:
        skill.bus.emit.reset_mock()
        skill.handle_search(make_message({"phrase": "aschenbrödel", "content_type": content_type}))
        skill.bus.emit.assert_called_once()


def test_handle_fetch_content_success(skill):
    skill.index = _sample_index()
    skill.get_story_paragraphs = MagicMock(return_value=["Es war einmal.", "Ende."])

    skill.handle_fetch_content(make_message({"content_id": "Aschenbrödel"}))

    sent = skill.bus.emit.call_args[0][0]
    assert sent.msg_type == COMMON_READING_FETCH_CONTENT_RESPONSE
    assert sent.data["paragraphs"] == ["Es war einmal.", "Ende."]


def test_handle_fetch_content_unknown_id_returns_empty(skill):
    skill.index = {}
    skill.handle_fetch_content(make_message({"content_id": "Nonexistent"}))
    sent = skill.bus.emit.call_args[0][0]
    assert sent.data["paragraphs"] == []


def test_handle_fetch_content_fetch_error_returns_empty(skill):
    skill.index = _sample_index()
    skill.get_story_paragraphs = MagicMock(side_effect=StoryFetchError("boom"))

    skill.handle_fetch_content(make_message({"content_id": "Aschenbrödel"}))

    sent = skill.bus.emit.call_args[0][0]
    assert sent.data["paragraphs"] == []
