"""Fetching a story: one request per book, the extracted text cached on
disk, a descriptive User-Agent, revalidation with If-Modified-Since, and
backing off when Project Gutenberg does not answer. No network: every
request is answered by FakeGutenberg (see conftest.py)."""
import gc
import json
import os
import threading
import time

import pytest
import requests
from bs4 import BeautifulSoup
from ovos_config.locations import get_xdg_cache_save_path

from conftest import StoryFetchError, fixture_page, response, skill_module
from test_bus_protocol import make_message

URL = "https://www.gutenberg.org/files/63465/63465-h/63465-h.htm"
LAST_MODIFIED = "Sat, 04 Mar 2023 15:20:10 GMT"
INDEX = {
    "Vom tapfern Schneiderlein": {"url": URL, "anchor": "chap_5"},
    "Die Kornähren": {"url": URL, "anchor": "chap_170"},
    "Aschenbrödel": {"url": URL, "anchor": "chap_364"},
    # not in the cut-down page
    "Das Dornröschen": {"url": URL, "anchor": "chap_311"},
}
ASCHENBROEDEL = INDEX["Aschenbrödel"]
SCHNEIDERLEIN = INDEX["Vom tapfern Schneiderlein"]
DORNROESCHEN = INDEX["Das Dornröschen"]


def book(last_modified=LAST_MODIFIED):
    return response(fixture_page("maerchenbuch.html"), last_modified=last_modified)


@pytest.fixture
def maerchen(skill, gutenberg):
    skill.index = dict(INDEX)
    gutenberg.pages[URL] = book()
    return skill


def cache_files(skill):
    return sorted(os.listdir(skill._story_cache.directory))


def age_cache(skill, seconds):
    for name in cache_files(skill):
        path = os.path.join(skill._story_cache.directory, name)
        with open(path, encoding="utf-8") as f:
            record = json.load(f)
        record["fetched_at"] -= seconds
        with open(path, "w", encoding="utf-8") as f:
            json.dump(record, f)


def end_backoff(skill):
    for key, (when, what) in list(skill._failures.items()):
        skill._failures[key] = (when - skill_module.FAILURE_BACKOFF - 1, what)


def test_a_book_is_fetched_once_for_all_its_stories(maerchen, gutenberg):
    aschenbroedel = maerchen.get_story_paragraphs(ASCHENBROEDEL)
    schneiderlein = maerchen.get_story_paragraphs(SCHNEIDERLEIN)
    maerchen.get_story_paragraphs(ASCHENBROEDEL)

    assert len(gutenberg.requests) == 1
    assert aschenbroedel[0].startswith("Ein Mann und eine Frau hatten zwei Töchter")
    assert schneiderlein[0].startswith("Es war einmal ein Schneiderlein")


def test_the_cache_holds_each_storys_text_not_the_page(maerchen, gutenberg):
    maerchen.get_story_paragraphs(ASCHENBROEDEL)

    files = cache_files(maerchen)
    assert len(files) == 3  # Dornröschen is not in the cut-down page
    for name in files:
        with open(os.path.join(maerchen._story_cache.directory, name), encoding="utf-8") as f:
            record = json.load(f)
        assert set(record) == {"format", "url", "anchor", "fetched_at", "last_modified", "paragraphs"}
        assert record["format"] == skill_module.CACHE_FORMAT
        assert record["last_modified"] == LAST_MODIFIED
        assert not any("<" in p for p in record["paragraphs"])


def test_the_cache_outlives_the_process(maerchen, gutenberg):
    expected = maerchen.get_story_paragraphs(SCHNEIDERLEIN)

    maerchen._init_story_cache(maerchen._story_cache.directory)  # a restart: nothing in memory
    assert maerchen.get_story_paragraphs(SCHNEIDERLEIN) == expected
    assert len(gutenberg.requests) == 1


def test_a_cache_written_by_another_format_is_fetched_again(maerchen, gutenberg, monkeypatch):
    maerchen.get_story_paragraphs(ASCHENBROEDEL)
    files = cache_files(maerchen)

    monkeypatch.setattr(skill_module, "CACHE_FORMAT", skill_module.CACHE_FORMAT + 1)
    maerchen._init_story_cache(maerchen._story_cache.directory)
    maerchen.get_story_paragraphs(ASCHENBROEDEL)

    assert len(gutenberg.requests) == 2
    # an extractor change must not be answered with a 304
    assert "If-Modified-Since" not in gutenberg.requests[1]["headers"]
    assert cache_files(maerchen) == files  # rewritten in place, not added to


def test_a_cache_entry_for_another_anchor_is_a_miss(maerchen, gutenberg):
    maerchen.get_story_paragraphs(ASCHENBROEDEL)

    moved = dict(ASCHENBROEDEL, anchor="chap_999")
    assert maerchen._story_cache.get(URL, moved["anchor"]) is None


def test_a_stale_story_is_asked_for_with_if_modified_since(maerchen, gutenberg):
    expected = maerchen.get_story_paragraphs(ASCHENBROEDEL)
    age_cache(maerchen, skill_module.CACHE_MAX_AGE + 60)
    gutenberg.pages[URL] = lambda headers: response(status=304)

    assert maerchen.get_story_paragraphs(ASCHENBROEDEL) == expected
    assert gutenberg.requests[1]["headers"]["If-Modified-Since"] == LAST_MODIFIED
    # the 304 renewed every story of that book, so none is asked for again
    maerchen.get_story_paragraphs(SCHNEIDERLEIN)
    assert len(gutenberg.requests) == 2


def test_a_stale_story_is_replaced_when_the_book_changed(maerchen, gutenberg):
    maerchen.get_story_paragraphs(ASCHENBROEDEL)
    age_cache(maerchen, skill_module.CACHE_MAX_AGE + 60)
    changed = fixture_page("maerchenbuch.html").replace("Stieftochter".encode(), "Pflegetochter".encode())
    gutenberg.pages[URL] = response(changed, last_modified="Sun, 09 Nov 2025 20:12:36 GMT")

    assert "auch noch eine Pflegetochter da" in maerchen.get_story_paragraphs(ASCHENBROEDEL)[0]
    assert maerchen._story_cache.get(URL, ASCHENBROEDEL["anchor"])["last_modified"] == "Sun, 09 Nov 2025 20:12:36 GMT"


def test_a_stale_copy_is_read_when_gutenberg_does_not_answer(maerchen, gutenberg):
    expected = maerchen.get_story_paragraphs(ASCHENBROEDEL)
    age_cache(maerchen, skill_module.CACHE_MAX_AGE + 60)
    gutenberg.pages[URL] = requests.ConnectionError("down")

    assert maerchen.get_story_paragraphs(ASCHENBROEDEL) == expected
    maerchen.log.warning.assert_called_once()


def test_a_failed_fetch_is_not_retried_before_the_backoff(maerchen, gutenberg):
    gutenberg.pages[URL] = requests.ConnectionError("down")

    with pytest.raises(StoryFetchError, match="down"):
        maerchen.get_story_paragraphs(ASCHENBROEDEL)
    # the same book, another story: no request
    with pytest.raises(StoryFetchError, match="not trying again"):
        maerchen.get_story_paragraphs(SCHNEIDERLEIN)
    assert len(gutenberg.requests) == 1

    end_backoff(maerchen)
    gutenberg.pages[URL] = book()
    assert maerchen.get_story_paragraphs(SCHNEIDERLEIN)
    assert len(gutenberg.requests) == 2


def test_an_http_error_is_a_failed_fetch(maerchen, gutenberg):
    gutenberg.pages[URL] = response(b"gone", status=404)

    with pytest.raises(StoryFetchError, match="404"):
        maerchen.get_story_paragraphs(ASCHENBROEDEL)
    with pytest.raises(StoryFetchError, match="not trying again"):
        maerchen.get_story_paragraphs(ASCHENBROEDEL)
    assert len(gutenberg.requests) == 1


def test_a_story_its_page_does_not_yield_does_not_refetch_the_book(maerchen, gutenberg):
    with pytest.raises(StoryFetchError, match="chap_311 not found"):
        maerchen.get_story_paragraphs(DORNROESCHEN)
    with pytest.raises(StoryFetchError, match="chap_311 not found"):
        maerchen.get_story_paragraphs(DORNROESCHEN)
    assert len(gutenberg.requests) == 1


def test_reading_works_when_the_cache_directory_cannot_be_written(maerchen, gutenberg, tmp_path):
    not_a_directory = tmp_path / "not-a-directory"
    not_a_directory.write_text("")
    maerchen._init_story_cache(str(not_a_directory / "story-cache"))

    assert maerchen.get_story_paragraphs(ASCHENBROEDEL)[0].startswith("Ein Mann und eine Frau hatten zwei Töchter")
    # the rest of that book is kept in memory: no second request for it
    assert maerchen.get_story_paragraphs(SCHNEIDERLEIN)[0].startswith("Es war einmal ein Schneiderlein")
    assert len(gutenberg.requests) == 1
    maerchen.log.warning.assert_called_once()


def test_the_user_agent_names_the_skill_its_version_and_repo(maerchen, gutenberg):
    maerchen.get_story_paragraphs(ASCHENBROEDEL)

    sent = gutenberg.requests[0]
    user_agent = sent["headers"]["User-Agent"]
    assert user_agent == skill_module.USER_AGENT
    assert user_agent.startswith(f"ovos-skill-bechstein-tales/{skill_module.SKILL_VERSION} ")
    assert "(+https://github.com/andlo/ovos-skill-bechstein-tales)" in user_agent
    assert "If-Modified-Since" not in sent["headers"]
    assert sent["timeout"] == skill_module.FETCH_TIMEOUT


def test_the_cache_is_in_the_skills_xdg_cache_directory(skill, monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg"))
    skill._init_story_cache()
    assert skill._story_cache.directory == os.path.join(get_xdg_cache_save_path(), "skills", skill.skill_id)
    assert skill._story_cache.directory.startswith(str(tmp_path / "xdg"))
    assert not os.path.exists(skill._story_cache.directory)  # made on first use


def test_no_parsed_page_is_kept(maerchen, gutenberg):
    gc.collect()
    before = sum(isinstance(o, BeautifulSoup) for o in gc.get_objects())
    maerchen.get_story_paragraphs(ASCHENBROEDEL)
    assert sum(isinstance(o, BeautifulSoup) for o in gc.get_objects()) == before


def test_two_stories_of_one_book_asked_at_once_fetch_it_once(maerchen, gutenberg):
    def slow_book(headers):
        time.sleep(0.2)
        return book()
    gutenberg.pages[URL] = slow_book
    results = {}
    threads = [threading.Thread(target=lambda e=e: results.update({e["anchor"]: maerchen.get_story_paragraphs(e)}))
               for e in (ASCHENBROEDEL, SCHNEIDERLEIN)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(results) == 2
    assert len(gutenberg.requests) == 1


def test_fetch_content_reply_keeps_its_shape(maerchen, gutenberg):
    maerchen.handle_fetch_content(make_message({"content_id": "Aschenbrödel"}))

    sent = maerchen.bus.emit.call_args[0][0]
    assert sent.msg_type == "ovos.common_reading.fetch_content.response"
    assert list(sent.data) == ["paragraphs"]
    assert sent.data["paragraphs"][-1].endswith("Wirf schöne Kleider über mich!“")
