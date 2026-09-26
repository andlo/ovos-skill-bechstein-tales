"""
skill OVOS Bechstein Tales
Copyright (C) 2026  Andreas Lorensen

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with this program.  If not, see <http://www.gnu.org/licenses/>.

---

Provider skill for ovos-common-reading-pipeline-plugin: implements the
ovos.common_reading.* bus protocol and registers NO intents of its own.
See https://github.com/andlo/ovos-common-reading-pipeline-plugin for the
full protocol - this skill has no standalone voice interface, it needs
the pipeline plugin installed and configured to be useful.

The story INDEX (title/anchor per story) is bundled with this package
(see locale/de-de/index.json), built once via scripts/build_index.py -
browsing/matching needs no internet at all. Internet is only needed when
actually fetching a specific story's text from Project Gutenberg.
"""

from ovos_workshop.skills import OVOSSkill
from ovos_bus_client.session import SessionManager
from ovos_utils.parse import match_one, fuzzy_match
from ovos_utils import classproperty
from ovos_utils.process_utils import RuntimeRequirements

import requests
from bs4 import BeautifulSoup
from functools import lru_cache
import re
import json
import os
import random
import unicodedata


class StoryFetchError(Exception):
    """Raised when a story could not be fetched or parsed from
    Project Gutenberg."""


COMMON_READING_SEARCH = "ovos.common_reading.search"
COMMON_READING_SEARCH_RESPONSE = "ovos.common_reading.search.response"
COMMON_READING_FETCH_CONTENT = "ovos.common_reading.fetch_content"  # + ".{this_skill_id}"
COMMON_READING_FETCH_CONTENT_RESPONSE = "ovos.common_reading.fetch_content.response"
COMMON_READING_PING = "ovos.common_reading.ping"
COMMON_READING_PONG = "ovos.common_reading.pong"

COLLECTION_ALIASES = ["bechstein", "ludwig bechstein"]
COLLECTION_HINT_THRESHOLD = 0.85
CONTENT_TYPES = ["story", "tale"]
AUTHOR_NAME = "Ludwig Bechstein"
COLLECTION_NAME = "Bechstein's Märchenbuch"
SOURCE_NAME = "Project Gutenberg"

# Bechstein's Märchenbuch is only sourced in German (see README) and this
# provider does NOT translate (unlike ovos-skill-ovosblog/
# ovos-skill-arxiv-papers) - it answers searches made in German and stays
# silent for every other language. That is decided per request, not once
# from the device's language: on a HiveMind hub one ovos-core serves many
# users at once, each session in its own language, so the provider always
# loads and looks at the language each search was made in (see
# _request_lang()). Same pattern as ovos-skill-andrew-lang-tales, just for
# 'de' instead of 'en'.
SUPPORTED_LANGUAGES = {"de"}

# 'erzähl mir ein Märchen' names no title: answer with a random one,
# confident enough to be read without an "is it that one?" round trip
# (the plugin asks below 0.8) but below the 1.0 of a title somebody
# actually named
RANDOM_STORY_CONFIDENCE = 0.9

# title matching ignores case, accents, punctuation, a leading article
# and a leading "Märchen vom"-style prefix, on both the request and the
# title - 'das märchen vom schlaraffenland', 'schlaraffenland' and 'Das
# Märchen vom Schlaraffenland' all compare as 'schlaraffenland'
LEADING_ARTICLES = ("der", "die", "das", "den", "dem", "des", "ein", "eine")
TITLE_PREFIXES = ("märchen von den", "märchen von dem", "märchen vom", "märchen von",
                  "von den", "von dem", "vom", "von")  # longest first
AND_WORD = "und"  # what '&' is read as
OR_WORD = "oder"  # 'Das Mäuslein Sambar, oder die treue Freundschaft der Tiere'
# a half of an 'X, oder Y' title, or the part before its first comma, is
# how people usually ask for it ('tischlein deck dich') - trusted a
# little less than the whole title, so a provider holding a story that is
# called exactly that still wins
PARTIAL_TITLE_WEIGHT = 0.95
# words that say nothing about which title was meant, half the titles
# have them ('der hase und der fuchs' is told apart by 'hase' and 'fuchs')
FILLER_WORDS = set(LEADING_ARTICLES) | {"und", "oder", "von", "vom", "im", "in", "mit",
                                        "zu", "zum", "zur", "am", "an", "auf", "aus"}
# two words are the same word when they are at least this alike
# ('aschenbroedel'/'aschenbrodel', 'haensel'/'hansel')
SAME_WORD_THRESHOLD = 0.9


def configured_languages(langs):
    """Primary subtags of the languages an installation is configured
    for (core lang + secondary_langs): ['en-US', 'fr-FR'] -> {'en', 'fr'}."""
    return {primary_subtag(lang) for lang in langs or [] if lang}


def primary_subtag(lang):
    """'en-US', 'en_gb', 'EN' -> 'en'."""
    return (lang or "").replace("_", "-").split("-")[0].lower()


def title_words(text):
    """Casefolded words, accents and punctuation dropped, '&' read as
    AND_WORD."""
    text = unicodedata.normalize("NFKD", text.casefold().replace("&", f" {AND_WORD} "))
    text = "".join(c for c in text if not unicodedata.combining(c))
    return re.sub(r"[\W_]+", " ", text).split()


def normalize_title(text):
    """Reduce a title (or what somebody asked for) to what matters for
    matching: its title_words(), without a leading article or one of
    TITLE_PREFIXES."""
    words = title_words(text)

    def drop_article(words):
        return words[1:] if len(words) > 1 and words[0] in LEADING_ARTICLES else words

    words = drop_article(words)
    for prefix in TITLE_PREFIXES:
        prefix = title_words(prefix)
        if len(words) > len(prefix) and words[:len(prefix)] == prefix:
            words = drop_article(words[len(prefix):])
            break
    return " ".join(words)


def significant_words(title):
    """The words of a normalized title that say which title it is -
    FILLER_WORDS are shared by half the titles and say nothing, unless
    the title has nothing else."""
    words = title.split()
    return [w for w in words if w not in FILLER_WORDS] or words


def same_word(a, b):
    if a == b:
        return True
    # a ratio can never beat the length ratio - skip the ones that cannot
    # make it before paying for the comparison
    if 2 * min(len(a), len(b)) < SAME_WORD_THRESHOLD * (len(a) + len(b)):
        return False
    return fuzzy_match(a, b) >= SAME_WORD_THRESHOLD


def title_similarity(wanted, alias):
    """How alike two normalized titles are, 0.0-1.0: the letter-level
    ratio averaged with the share of significant_words() that have a
    close match on the other side. Letters alone are too generous -
    'schneewittchen' and 'Schneeweißchen' are 0.83 alike letter by letter
    but not the same word (0.41 together), 'der hahn und der hase' and
    'Der Hahn und der Fuchs' 0.86 but share one of two words (0.68).
    Spaces do not count ('rot käppchen' is 'Das Rotkäppchen')."""
    if wanted.replace(" ", "") == alias.replace(" ", ""):
        return 1.0
    a, b = significant_words(wanted), significant_words(alias)
    shared = sum(any(same_word(w, o) for o in b) for w in a) + \
        sum(any(same_word(w, o) for o in a) for w in b)
    return (fuzzy_match(wanted, alias) + shared / (len(a) + len(b))) / 2


@lru_cache(maxsize=None)
def title_aliases(title):
    """Every way a title can be asked for, normalized, each with the
    weight its match counts for: the whole title, and at
    PARTIAL_TITLE_WEIGHT each half of an 'X, oder Y' / 'X; Y' / 'X. Y'
    title and the part before its first comma ('Tischlein deck dich,
    Esel streck dich, ...'). Anything in parentheses is not part of the
    name."""
    whole = re.sub(r"\([^)]*\)", " ", title)
    aliases = {normalize_title(title): 1.0, normalize_title(whole): 1.0}
    parts = re.split(rf"[;:.]|\b{OR_WORD}\b", whole, flags=re.IGNORECASE)
    parts.append(whole.split(",")[0])
    for part in parts:
        alias = normalize_title(part)
        if alias and alias not in aliases:
            aliases[alias] = PARTIAL_TITLE_WEIGHT
    aliases.pop("", None)
    return tuple(aliases.items())


class BechsteinTales(OVOSSkill):

    @classproperty
    def runtime_requirements(self):
        # the story index is bundled - browsing/matching needs no
        # internet. Internet is only needed when actually fetching a
        # specific story's text, handled per-request with a graceful
        # fallback (see handle_fetch_content).
        return RuntimeRequirements(
            internet_before_load=False,
            network_before_load=False,
            requires_internet=False,
            requires_network=False,
            no_internet_fallback=True,
            no_network_fallback=True,
        )

    def initialize(self):
        # Loads only when German is one of the languages this installation
        # is configured for: the device's own 'lang' plus 'secondary_langs'
        # in mycroft.conf. A single English device never loads a German-only
        # provider; a HiveMind hub serving German-speaking users lists
        # 'de-..' in secondary_langs. Once loaded, each request's own
        # language still decides whether it is answered (handle_search()).
        self.served = configured_languages(self.native_langs) & SUPPORTED_LANGUAGES
        if not self.served:
            self.log.info(
                f"{self.skill_id}: none of the configured languages "
                f"{sorted(self.native_langs)} is German (de-*) - "
                f"add it to 'secondary_langs' in mycroft.conf to serve "
                f"German-speaking sessions. Skill stays inert (no bus "
                f"events registered, index not loaded)."
            )
            self.index = {}
            return
        self._book_soup_cache = {}
        self.index = self._load_index()
        if not self.index:
            self.log.error("No bundled story index found")
        self.log.info(
            f"{self.skill_id}: serving {len(self.index)} German stories "
            f"to searches made in German (de-*)"
        )
        self.add_event(COMMON_READING_SEARCH, self.handle_search)
        self.add_event(f"{COMMON_READING_FETCH_CONTENT}.{self.skill_id}", self.handle_fetch_content)
        self.add_event(COMMON_READING_PING, self.handle_ping)

    def _load_index(self):
        path = os.path.join(os.path.dirname(__file__), "locale", "de-de", "index.json")
        if not os.path.isfile(path):
            return {}
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (OSError, ValueError) as e:
            self.log.error(f"could not read bundled story index {path}: {e}")
            return {}

    def _get_book_soup(self, url):
        if url in self._book_soup_cache:
            return self._book_soup_cache[url]
        try:
            r = requests.get(url, timeout=15)
            r.raise_for_status()
            # the page is UTF-8 but doesn't declare a charset in its HTTP
            # headers, so requests defaults to ISO-8859-1 and mangles
            # non-ASCII text ('Aschenbrödel' -> 'AschenbrÃ¶del') without this
            r.encoding = "utf-8"
            soup = BeautifulSoup(r.text, "html.parser")
        except requests.RequestException as e:
            raise StoryFetchError(f"failed to fetch {url}: {e}") from e
        self._book_soup_cache[url] = soup
        return soup

    def get_story_paragraphs(self, entry):
        """Extract a single story's paragraphs from its <div class='chapter'>.
        Unlike ovos-skill-andrew-lang-tales' flat-HTML anchor scheme, this
        book properly nests each story's content inside its own div, so we
        can just grab every <p> inside it directly - no need to guess where
        the story ends by looking for the next anchor.

        Text extraction uses get_text(strip=True) WITHOUT a separator - a
        real bug found while building this: with separator=' ', drop-cap
        spans like '<span class="drop">E</span>s war einmal' become 'E s
        war einmal' (spurious space at the tag boundary, splitting the
        first word). No separator avoids that, but leaves the original
        HTML's line-wrapped whitespace (literal newlines) embedded in the
        text, which the regex below collapses to single spaces."""
        soup = self._get_book_soup(entry["url"])
        div = soup.find("div", {"class": "chapter", "id": entry["anchor"]})
        if div is None:
            raise StoryFetchError(f"chapter {entry['anchor']} not found in {entry['url']}")
        paragraphs = []
        for p in div.find_all("p"):
            text = re.sub(r"\s+", " ", p.get_text(strip=True)).strip()
            if text:
                paragraphs.append(text)
        if not paragraphs:
            raise StoryFetchError(f"no story text found at {entry['url']}#{entry['anchor']}")
        return paragraphs

    def _matches_collection_hint(self, hint):
        if not hint:
            return True
        _, score = match_one(hint.lower(), COLLECTION_ALIASES)
        return score >= COLLECTION_HINT_THRESHOLD

    def _matches_content_type(self, content_type):
        if not content_type:
            return True
        return content_type.lower() in CONTENT_TYPES

    @staticmethod
    def _request_lang(message):
        """The language a request was made in, or None when it does not
        say: the pipeline plugin's own 'lang' field first, then the
        language of the session the request was forwarded from (a
        HiveMind client's, on a hub). An older plugin sends neither."""
        lang = message.data.get("lang") or message.context.get("lang")
        if not lang and message.context.get("session"):
            lang = SessionManager.get(message).lang
        return lang or None

    def _serves(self, lang):
        return primary_subtag(lang) in self.served

    def _best_title(self, phrase):
        """(title, confidence) of the story that best matches what was
        asked for, or (None, 0.0) when the phrase is empty once
        normalized - see normalize_title() and title_aliases()."""
        wanted = normalize_title(phrase)
        best, best_score = None, 0.0
        if not wanted:
            return best, best_score
        for title in self.index:
            for alias, weight in title_aliases(title):
                score = title_similarity(wanted, alias) * weight
                if score > best_score:
                    best, best_score = title, score
        return best, best_score

    def handle_search(self, message):
        if not self.index:
            return
        # a search made in any other language gets no answer at all, not
        # an empty one - the plugin just collects whatever arrives. With
        # no language on the request (an older plugin), the device's own
        # language decides, as it always did.
        if not self._serves(self._request_lang(message) or self.lang):
            return
        collection_hint = message.data.get("collection_hint")
        if not self._matches_collection_hint(collection_hint):
            return
        content_type = message.data.get("content_type")
        if not self._matches_content_type(content_type):
            return

        phrase = (message.data.get("phrase") or "").strip()
        title, confidence = self._best_title(phrase) if phrase else (None, 0.0)
        if title is None:
            # no title asked for: 'tell me a story', or 'a story from
            # Bechstein' - a random one, and fully confident when the
            # collection itself was named
            title = random.choice(list(self.index.keys()))
            confidence = 1.0 if collection_hint else RANDOM_STORY_CONFIDENCE

        self.bus.emit(message.reply(COMMON_READING_SEARCH_RESPONSE, {
            "skill_id": self.skill_id,
            "content_id": title,
            "title": title,
            "author": AUTHOR_NAME,
            "collection": COLLECTION_NAME,
            "source": SOURCE_NAME,
            "confidence": confidence,
        }))

    def handle_fetch_content(self, message):
        content_id = message.data.get("content_id")
        entry = self.index.get(content_id)
        if not entry:
            self.bus.emit(message.reply(COMMON_READING_FETCH_CONTENT_RESPONSE, {"paragraphs": []}))
            return
        try:
            paragraphs = self.get_story_paragraphs(entry)
        except StoryFetchError as e:
            self.log.error(f"Could not fetch story '{content_id}': {e}")
            self.bus.emit(message.reply(COMMON_READING_FETCH_CONTENT_RESPONSE, {"paragraphs": []}))
            return
        self.bus.emit(message.reply(COMMON_READING_FETCH_CONTENT_RESPONSE, {"paragraphs": paragraphs}))

    def handle_ping(self, message):
        """Cheap 'is anyone there?' reply - no index lookup. Only ever
        called by the pipeline plugin on its rare 0-candidates path
        (see ovos-common-reading-pipeline-plugin#2), never on every
        search. A ping that says which language it is asking for (its
        'lang' field or the session it was forwarded from) only gets a
        pong when that is German, so the plugin can tell 'nothing
        installed for this language' from 'found nothing'. A ping that
        does not say is answered: this provider is installed."""
        lang = self._request_lang(message)
        if lang and not self._serves(lang):
            return
        self.bus.emit(message.reply(COMMON_READING_PONG, {
            "skill_id": self.skill_id,
            "collection": COLLECTION_NAME,
        }))
