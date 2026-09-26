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
> blog post or abstract. **It answers searches made in German (`de-*`)
> and stays silent for every other language**, and only loads
> where German is configured - the device language or `secondary_langs` (see "Languages" below).

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

## Languages

The provider loads only where German is one of the languages the
installation is configured for: the device's own `lang`, or one of
`secondary_langs` in `mycroft.conf`. A single device in another
language never loads it. A HiveMind hub whose users speak German lists
it there, even when the hub's own language is something else:

```json
{
  "lang": "en-US",
  "secondary_langs": ["de-DE"]
}
```

Once loaded, it decides **per search** whether to answer:
a search made in German gets an answer, any other language gets none.
The language of a search is the pipeline plugin's `lang` field, else the
language of the session the search came from, else (an older plugin
sends neither) the device's own language. That matters on a HiveMind
hub, where one ovos-core serves many users at once, each session in its
own language: a German session must get these stories on a hub whose own
language is English, and a French session must not get German ones. A
`ping` that names a language (the same way) only gets a pong when that
is German. Fetching a story is never gated on language - it is addressed
to this provider directly.

## Title matching

Titles match regardless of case, umlauts, punctuation, a leading article
and a leading "Märchen vom" / "Vom" / "Von", so "rotkäppchen" finds *Das
Rotkäppchen* and "schlaraffenland" *Das Märchen vom Schlaraffenland* at
full confidence. The part before a title's first comma, or either half
of an "X, oder Y" title, counts too, slightly below the whole title:
"tischlein deck dich" finds *Tischlein deck dich, Esel streck dich,
Knüppel aus dem Sack*. A search that names no title at all ("erzähl mir
ein Märchen") gets one random story at confidence 0.9, or 1.0 when it
named this collection.

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
