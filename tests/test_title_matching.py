"""Title matching against the real bundled index (80 stories): case,
umlauts, punctuation and a leading article do not matter, and the short
name people use for a long title finds it."""
import pytest
from ovos_bus_client.message import Message

from conftest import normalize_title, title_aliases

CONFIRMATION_THRESHOLD = 0.8  # the pipeline plugin asks "is it that one?" below this


@pytest.fixture
def indexed(skill):
    skill.index = skill._load_index()
    return skill


@pytest.mark.parametrize("phrase", ["Aschenbrödel", "aschenbrödel", "ASCHENBRÖDEL", "aschenbrodel"])
def test_exact_title_in_any_case(indexed, phrase):
    assert indexed._best_title(phrase) == ("Aschenbrödel", 1.0)


@pytest.mark.parametrize("phrase, expected", [
    ("rotkäppchen", "Das Rotkäppchen"),
    ("das rotkäppchen", "Das Rotkäppchen"),
    ("hänsel und gretel", "Hänsel und Gretel"),
    ("die sieben geißlein", "Die sieben Geißlein"),
    ("schlaraffenland", "Das Märchen vom Schlaraffenland"),
    ("tischlein deck dich", "Tischlein deck dich, Esel streck dich, Knüppel aus dem Sack"),
    ("der teufel ist los", "Der Teufel ist los oder Das Märlein, wie der Teufel den Branntwein erfand"),
])
def test_name_people_use_finds_the_title(indexed, phrase, expected):
    title, score = indexed._best_title(phrase)
    assert title == expected
    assert score >= 0.95


@pytest.mark.parametrize("phrase, expected", [
    ("aschenbroedel", "Aschenbrödel"),
    ("haensel und gretel", "Hänsel und Gretel"),
    ("hans im glück", "Hans im Glücke"),
])
def test_close_spelling_still_confident(indexed, phrase, expected):
    title, score = indexed._best_title(phrase)
    assert title == expected
    assert score >= CONFIRMATION_THRESHOLD


@pytest.mark.parametrize("phrase", [
    # Snow White, not Snow-White of 'Snow-White and Rose-Red'
    "schneewittchen",
    # not in this collection: 'Der Hase und der Fuchs' shares one of two words
    "der hase und der igel",
])
def test_a_different_story_is_not_read_without_asking(indexed, phrase):
    _, score = indexed._best_title(phrase)
    assert score < CONFIRMATION_THRESHOLD


def test_search_response_keeps_the_index_title_as_content_id(indexed):
    indexed.handle_search(Message("ovos.common_reading.search", {"phrase": "rotkäppchen"}))
    sent = indexed.bus.emit.call_args[0][0]
    assert sent.data["content_id"] == "Das Rotkäppchen"
    assert sent.data["title"] == "Das Rotkäppchen"
    assert sent.data["confidence"] == 1.0


@pytest.mark.parametrize("text, expected", [
    ("Das Märchen vom Schlaraffenland", "schlaraffenland"),
    ("Vom tapfern Schneiderlein", "tapfern schneiderlein"),
    ("Schneeweißchen", "schneeweisschen"),
    ("Schwan, kleb’ an!", "schwan kleb an"),
    ("Hänsel & Gretel", "hansel und gretel"),
])
def test_normalize_title(text, expected):
    assert normalize_title(text) == expected


def test_title_aliases_of_an_either_or_title():
    aliases = dict(title_aliases("Das Mäuslein Sambar, oder die treue Freundschaft der Tiere"))
    assert aliases["mauslein sambar oder die treue freundschaft der tiere"] == 1.0
    assert aliases["mauslein sambar"] < 1.0
    assert aliases["treue freundschaft der tiere"] < 1.0
