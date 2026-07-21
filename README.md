# <img src='story-512.png' card_color='#40DBB0' width='50' height='50' style='vertical-align:bottom'/> Bechstein Tales (provider)

A *provider* skill for [ovos-common-reading-pipeline-plugin](https://github.com/andlo/ovos-common-reading-pipeline-plugin),
delivering Ludwig Bechstein's German fairy tales.

Bechstein was a contemporary of the Brothers Grimm and published his own
hugely popular collection - a genuinely different source, not just "more
Grimm" (though a few titles overlap, since both drew from the same
regional oral tradition).

[![Tests](https://github.com/andlo/ovos-skill-bechstein-tales/actions/workflows/test.yml/badge.svg)](https://github.com/andlo/ovos-skill-bechstein-tales/actions/workflows/test.yml)
[![PyPI version](https://img.shields.io/pypi/v/ovos-skill-bechstein-tales.svg)](https://pypi.org/project/ovos-skill-bechstein-tales/)

> **This skill has no standalone voice interface.** It registers no
> intents and never speaks. It only answers
> [ovos.common_reading.* bus messages](https://github.com/andlo/ovos-common-reading-pipeline-plugin#the-ovoscommon_reading-bus-protocol),
> so you also need **ovos-common-reading-pipeline-plugin** installed and
> added to your pipeline config for it to be useful at all.

> **German only, no translation.** Same situation as
> `ovos-skill-andrew-lang-tales`, just for German instead of English -
> full fairy tale prose is a bigger translation cost/quality risk than a
> blog post or abstract. **On any device language other than German,
> this provider never loads at all**: `initialize()` checks the device's
> language against `SUPPORTED_LANGUAGES = {"de"}` before loading the
> index or registering any bus events, logging why. Set your OVOS
> device's language to German (`de-*`) to use this provider.

## Install
```bash
pip install ovos-skill-bechstein-tales ovos-common-reading-pipeline-plugin
```

## Story index

The story index (title, anchor per story) is **bundled with this
package** (`locale/de-de/index.json`), not scraped live - browsing/
matching needs no internet at all. Only fetching a specific story's
actual text (once chosen) needs a live request to Project Gutenberg.

**80 stories** from Ludwig Bechstein's Märchenbuch (Project Gutenberg
ebook #63465). The index was built once via `scripts/build_index.py`,
which parses the book's own "Inhalt" (table of contents) table rather
than assuming every `<div class="chapter">` is a real story - one entry
("Alphabetisches Verzeichnis der Märchen", the book's own index) was
correctly excluded this way since it has no story paragraphs.

Two real bugs were found and fixed while building this:
- **Encoding**: the Gutenberg page doesn't declare a charset in its HTTP
  headers, so `requests` defaulted to ISO-8859-1 and mangled German
  text (`Aschenbrödel` → `AschenbrÃ¶del`). Fixed by setting
  `r.encoding = "utf-8"` explicitly.
- **Drop caps**: `get_text(' ', strip=True)` inserts a spurious space at
  drop-cap span boundaries (`<span>E</span>s war einmal` → `E s war
  einmal`, splitting the first word). Fixed by extracting text with no
  separator and instead collapsing the source HTML's line-wrapped
  whitespace with a regex - the same class of bug as
  `ovos-skill-ovosblog`'s inline-`<code>` finding, different cause.

## Collection hints

Responds to `collection_hint` values like "bechstein", "ludwig
bechstein", matched fuzzily (see `COLLECTION_ALIASES` in `__init__.py`).

## Content type

Identifies as `content_type: "story"` or `"tale"`. A search with a
`content_type` hint for anything else gets no response from this
provider.

## Credits

Content sourced from [Project Gutenberg](https://www.gutenberg.org/).
Scraping/extraction/caching logic ported from
[ovos-skill-andrew-lang-tales](https://github.com/andlo/ovos-skill-andrew-lang-tales).

## Category
**Entertainment**

## Tags
#stories #fairytales #bechstein #german #provider
