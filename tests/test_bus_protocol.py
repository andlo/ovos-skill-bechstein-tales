"""Tests for the ovos.common_reading.* bus protocol handlers."""
from unittest.mock import MagicMock

from conftest import COMMON_READING_SEARCH_RESPONSE, COMMON_READING_FETCH_CONTENT_RESPONSE, COMMON_READING_PONG, StoryFetchError


def make_message(data=None, context=None):
    m = MagicMock()
    m.data = data or {}
    m.context = context or {}
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


def test_handle_search_surprise_me_with_matching_hint_is_fully_confident(skill):
    skill.index = _sample_index()
    skill.handle_search(make_message({"phrase": None, "collection_hint": "bechstein"}))
    assert skill.bus.emit.call_args[0][0].data["confidence"] == 1.0


def test_handle_search_no_phrase_no_hint_picks_one_random_story(skill):
    """'erzähl mir ein Märchen' - no title, no collection: one random
    story at 0.9, enough to be read without an 'is it that one?' round trip."""
    skill.index = _sample_index()
    for data in [{"phrase": None, "collection_hint": None},
                 {"phrase": None, "content_type": "story"},
                 {"phrase": ""},
                 {"phrase": "   "},
                 {}]:
        skill.bus.emit.reset_mock()
        skill.handle_search(make_message(data))
        skill.bus.emit.assert_called_once()
        sent = skill.bus.emit.call_args[0][0]
        assert sent.msg_type == COMMON_READING_SEARCH_RESPONSE
        assert sent.data["content_id"] in skill.index
        assert sent.data["confidence"] == 0.9


def test_handle_search_no_phrase_other_content_type_stays_silent(skill):
    skill.index = _sample_index()
    skill.handle_search(make_message({"phrase": None, "content_type": "horoscope"}))
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


def test_handle_ping_replies_with_pong(skill):
    skill.handle_ping(make_message())

    sent = skill.bus.emit.call_args[0][0]
    assert sent.msg_type == COMMON_READING_PONG
    assert sent.data["skill_id"] == skill.skill_id
    assert sent.data["collection"] == "Bechstein's Märchenbuch"


def test_handle_ping_does_not_touch_the_index(skill):
    skill.index = None

    skill.handle_ping(make_message())

    skill.bus.emit.assert_called_once()
