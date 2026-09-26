"""Tests for extract_book() - includes a regression case for a real bug
found while building this: get_text(' ', strip=True) inserts a spurious
space at drop-cap span boundaries ('<span>E</span>s war einmal' -> 'E s
war einmal'), and the source HTML's line-wrapped text nodes contain
literal newlines that need collapsing. test_text_cleanup.py runs it on a
cut-down real page."""
from conftest import extract_book

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
""".encode("utf-8")


def test_extract_book_fixes_dropcap_and_linewrap():
    stories, errors = extract_book(SAMPLE_HTML, ["chap_1", "chap_2"])

    assert errors == {}
    assert stories["chap_1"][0] == "Es war einmal ein Mann und eine Frau, die hatten zwei Töchter."
    assert stories["chap_1"][1] == "Und die Stieftochter war fromm und gut."


def test_extract_book_scoped_to_correct_chapter_div():
    stories, _ = extract_book(SAMPLE_HTML, ["chap_1", "chap_2"])

    assert stories["chap_2"] == ["Es waren vor Zeiten ein König und eine Königin."]


def test_extract_book_missing_anchor_is_an_error_for_that_story_only():
    stories, errors = extract_book(SAMPLE_HTML, ["chap_2", "chap_999"])

    assert list(stories) == ["chap_2"]
    assert "chap_999" in errors["chap_999"]


def test_the_page_is_read_as_utf8():
    """The page is UTF-8 but its HTTP headers do not say so: requests
    alone would read 'Aschenbrödel' as 'AschenbrÃ¶del'."""
    stories, _ = extract_book(SAMPLE_HTML, ["chap_1"])
    assert "Töchter" in stories["chap_1"][0]
