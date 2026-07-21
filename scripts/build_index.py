#!/usr/bin/env python3
"""Builds locale/de-de/index.json - a bundled title -> {url, anchor}
mapping for Ludwig Bechstein's Märchenbuch (Project Gutenberg #63465).
Run once at dev time; the generated index.json is what actually ships
with the package (no internet needed to browse/match titles - see
ovos-skill-andrew-lang-tales, same pattern).

Book structure (verified by hand before writing this script): the whole
book is one HTML page. Each story is `<div class='chapter' id='chap_N'>`
containing an `<h2>` title and its `<p>` paragraphs. A table of contents
("Inhalt", itself also wrapped in a chapter div - excluded here) lists
every real story as {title: '#chap_N'} - using that table directly is
more reliable than assuming every div.chapter is a real story."""
import json
import requests
from bs4 import BeautifulSoup

BOOK_URL = "https://www.gutenberg.org/files/63465/63465-h/63465-h.htm"


def build_index():
    r = requests.get(BOOK_URL, timeout=30)
    r.raise_for_status()
    r.encoding = "utf-8"  # the page is UTF-8 but doesn't declare a charset in
    # its HTTP headers, so requests defaults to ISO-8859-1 and mangles
    # non-ASCII text (e.g. 'Aschenbrödel' -> 'AschenbrÃ¶del') without this
    soup = BeautifulSoup(r.text, "html.parser")

    toc_table = soup.find("table")
    if toc_table is None:
        raise RuntimeError("could not find the Inhalt (table of contents) table")

    index = {}
    for row in toc_table.find_all("tr")[1:]:  # skip header row
        cells = row.find_all("td")
        if len(cells) != 2:
            continue
        title = cells[0].get_text(strip=True)
        link = cells[1].find("a")
        if not link or not title:
            continue
        anchor = link.get("href", "").lstrip("#")
        if not anchor:
            continue
        # validate: does this anchor actually resolve to real paragraph text?
        div = soup.find("div", {"class": "chapter", "id": anchor})
        if div is None or not div.find_all("p"):
            print(f"  skipping '{title}' ({anchor}) - no paragraph text found")
            continue
        index[title] = {"url": BOOK_URL, "anchor": anchor}

    return index


if __name__ == "__main__":
    index = build_index()
    print(f"Built index with {len(index)} stories")
    with open("locale/de-de/index.json", "w", encoding="utf-8") as f:
        json.dump(index, f, ensure_ascii=False, indent=2, sort_keys=True)
    print("Wrote locale/de-de/index.json")
