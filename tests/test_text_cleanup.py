"""What a story reads like once extracted, on the real page from
gutenberg.org cut down to three stories (tests/fixtures/). Each test
names what the old extractor did with the same page."""
from conftest import extract_book, fixture_page

ANCHORS = ["chap_5", "chap_170", "chap_364"]


def story(anchor):
    stories, errors = extract_book(fixture_page("maerchenbuch.html"), ANCHORS)
    assert anchor in stories, errors
    return stories[anchor]


def test_page_numbers_are_not_read():
    """Page numbers are <span class="pagenum">s in the middle of the
    text: 'Als nun die368Braut aus der Kirche ging' - 416 of them in the
    80 stories."""
    paragraphs = story("chap_364")
    assert paragraphs[1].endswith("und wenn Aschenbrödel auf dem Grab ihrer Mutter weinte, "
                                  "so kam allemal ein Vöglein geflogen, das sah sie mitleidig an.")
    assert not any(c.isdigit() for p in paragraphs for c in p)


def test_words_either_side_of_a_tag_stay_apart():
    """'der Held habe sieben Männer auf <span class="emphasis">einen</span>
    Streich' used to read 'aufeinenStreich': every piece of text was
    stripped before they were glued together."""
    first = story("chap_5")[0]
    assert "der Held habe sieben Männer auf einen Streich gefällt" in first
    assert "Hölle fallen lassen" in first  # a page number was between these


def test_a_drop_cap_stays_part_of_its_word():
    assert story("chap_5")[0].startswith("Es war einmal ein Schneiderlein, das saß in einer Stadt,")


def test_verse_is_read_line_by_line():
    """Verse is <div class="verse">, not <p>, and was never read: the
    bird's promise and Aschenbrödel's wish were skipped."""
    paragraphs = story("chap_364")
    assert "„Mein liebes Kind, o sage mir,\nWas du dir wünschest, schenk’ ich dir!“" in paragraphs
    assert paragraphs[-1] == ("„O liebes Bäumchen, rüttle dich!\nO liebes Bäumchen, schüttle dich!\n"
                              "Wirf schöne Kleider über mich!“")
    assert paragraphs.index("Da rief Aschenbrödel, indem sie das Bäumchen anfaßte:") == len(paragraphs) - 2


def test_a_footnote_and_its_number_are_not_read():
    """'nicht zum Verurzen[1] und dachte', and the story used to end on
    the footnote: '[1] Mutwillig verderben.'"""
    paragraphs = story("chap_170")
    assert "und dem Vieh zum Futter und nicht zum Verurzen und dachte bei sich" in paragraphs[-1]
    assert not any("[1]" in p or "Mutwillig" in p for p in paragraphs)
