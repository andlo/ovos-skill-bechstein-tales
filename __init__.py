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

from ovos_config.locations import get_xdg_cache_save_path
from ovos_workshop.skills import OVOSSkill
from ovos_bus_client.session import SessionManager
from ovos_utils.parse import match_one, fuzzy_match
from ovos_utils import classproperty
from ovos_utils.process_utils import RuntimeRequirements

import requests
from bs4 import BeautifulSoup
from functools import lru_cache
import re
import gc
import hashlib
import importlib.metadata
import json
import os
import random
import threading
import time
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


# --- fetching a story's text -------------------------------------------------
#
# Project Gutenberg's robot policy discourages automated access, and the
# text of a public-domain book does not change. So a book is fetched at
# most once per CACHE_MAX_AGE, whichever of its stories was asked for, and
# what is kept is the text each of its stories extracts to - one small
# file per story under the skill's XDG cache directory - never the page
# (up to 793 KB) or its parse tree (~6 MB in memory).

PYPI_NAME = "ovos-skill-bechstein-tales"
REPO_URL = "https://github.com/andlo/ovos-skill-bechstein-tales"
try:
    SKILL_VERSION = importlib.metadata.version(PYPI_NAME)
except importlib.metadata.PackageNotFoundError:  # run from a checkout
    SKILL_VERSION = "unknown"
# says who is asking and where to find them, instead of python-requests/x
USER_AGENT = f"{PYPI_NAME}/{SKILL_VERSION} (+{REPO_URL})"
FETCH_TIMEOUT = 15  # seconds
# bump whenever a story would extract to different text, so that what an
# older release cached is fetched again rather than read out as it was
CACHE_FORMAT = 1
# a story cached longer ago than this is asked for again, with the page's
# Last-Modified - an unchanged page answers 304, without a body
CACHE_MAX_AGE = 30 * 24 * 3600
# a book that failed to arrive is not asked for again before this, so a
# Gutenberg outage costs one request every few minutes, not one per story
# asked for
FAILURE_BACKOFF = 5 * 60


class StoryCache:
    """The paragraphs each story extracted to, as one small JSON file per
    story in `directory`, named after where the story is (its book URL
    and anchor). A file written for another CACHE_FORMAT, URL or anchor is
    a miss. It never holds more files than the bundled index has stories.

    When `directory` cannot be written, the stories of the last book
    fetched are kept in memory instead - text only, a small part of what
    the parsed page took - so reading still works."""

    def __init__(self, directory, log):
        self.directory = directory
        self.log = log
        self._memory = {}
        self._warned = False

    @staticmethod
    def _name(url, anchor):
        return hashlib.sha256(f"{url}#{anchor}".encode("utf-8")).hexdigest()[:32] + ".json"

    def get(self, url, anchor):
        """The cached record for a story, fresh or not, or None."""
        name = self._name(url, anchor)
        record = self._memory.get(name)
        if record is None:
            try:
                with open(os.path.join(self.directory, name), encoding="utf-8") as f:
                    record = json.load(f)
            except (OSError, ValueError):
                return None
        if not isinstance(record, dict) or record.get("format") != CACHE_FORMAT \
                or record.get("url") != url or record.get("anchor") != anchor \
                or not isinstance(record.get("fetched_at"), (int, float)) \
                or not record.get("paragraphs"):
            return None
        return record

    @staticmethod
    def is_fresh(record):
        return 0 <= time.time() - record["fetched_at"] < CACHE_MAX_AGE

    def put(self, records):
        """Store the records of one book's stories."""
        try:
            os.makedirs(self.directory, exist_ok=True)
            for record in records:
                path = os.path.join(self.directory, self._name(record["url"], record["anchor"]))
                tmp = f"{path}.{os.getpid()}.tmp"
                try:
                    with open(tmp, "w", encoding="utf-8") as f:
                        json.dump(record, f, ensure_ascii=False)
                    os.replace(tmp, path)
                except OSError:
                    if os.path.exists(tmp):
                        os.remove(tmp)
                    raise
        except OSError as e:
            if not self._warned:
                self.log.warning(f"cannot write the story cache in {self.directory} ({e}), "
                                 f"keeping the last book fetched in memory instead")
                self._warned = True
            self._memory = {self._name(r["url"], r["anchor"]): r for r in records}


# --- extracting a story's text -----------------------------------------------

LINE_BREAK = "\u2028"  # what a <br> becomes, to tell it from the HTML's own wrapping
# 'nicht zum Verurzen[1] und', 'sieben Wackelsteine[2] geholt': the number
# of a footnote, which is not read (see story_paragraphs()), so neither
# is the number
FOOTNOTE_MARKER = re.compile(r"\s*\[\d{1,3}\]")


def paragraph_text(el):
    """An element's text as it should be read: every run of whitespace is
    one space - the page's own line breaks are only where the HTML was
    wrapped - and only a <br> (LINE_BREAK, see extract_book()) starts a
    new line.

    Taken with get_text() and no separator: with separator=' ', drop-cap
    spans like '<span class="drop">E</span>s war einmal' become 'E s war
    einmal'. The old get_text(strip=True) avoided that but stripped each
    piece of text before gluing them, so a word before an inline tag was
    glued to the one after it: 'Als nun die<span class="pagenum">368
    </span>Braut' was read 'Als nun die368Braut'."""
    lines = (" ".join(line.split()) for line in el.get_text().split(LINE_BREAK))
    return "\n".join(line for line in lines if line)


def stanza_text(el):
    """A stanza of the verse in a tale ('Bäumlein, rüttel dich und
    schüttel dich, ...' in Aschenbrödel), one line per line of verse.
    Verse is in <div class="verse">, not <p>, and was never read."""
    lines = (paragraph_text(verse) for verse in el.find_all("div", class_="verse"))
    return "\n".join(line for line in lines if line)


def story_paragraphs(soup, anchor):
    """Extract a single story's paragraphs from its <div class='chapter'>.
    Unlike ovos-skill-andrew-lang-tales' flat-HTML anchor scheme, this
    book properly nests each story's content inside its own div, so we
    can just take its paragraphs and stanzas in order - no need to guess
    where the story ends by looking for the next anchor. The book's two
    footnotes (<p class="footnote">) are left out."""
    div = soup.find("div", {"class": "chapter", "id": anchor})
    if div is None:
        raise StoryFetchError(f"chapter {anchor} not found")
    paragraphs = []
    for el in div.find_all(["p", "div"]):
        classes = el.get("class") or []
        if el.name == "p" and "footnote" not in classes and el.find_parent("div", class_="stanza") is None:
            text = paragraph_text(el)
        elif el.name == "div" and "stanza" in classes:
            text = stanza_text(el)
        else:
            continue
        text = FOOTNOTE_MARKER.sub("", text).strip()
        if text:
            paragraphs.append(text)
    if not paragraphs:
        raise StoryFetchError(f"no story text found in chapter {anchor}")
    return paragraphs


def extract_book(content, anchors):
    """Every story of the book in one go - ({anchor: paragraphs}, {anchor:
    what went wrong}) - from the page's bytes, so the book never has to be
    fetched again for another of its stories. The page is UTF-8 but does
    not say so in its HTTP headers (requests then assumes ISO-8859-1 and
    reads 'Aschenbrödel' as 'AschenbrÃ¶del'). Page numbers are
    <span class="pagenum">s in the middle of the text - 416 of them in the
    80 stories - and are dropped before anything is read. The parse
    tree is ~6 MB of reference cycles that only the cycle collector frees,
    so it is collected before returning (~20 ms, once per fetch) rather
    than whenever the collector next gets to it."""
    soup = BeautifulSoup(content, "html.parser", from_encoding="utf-8")
    try:
        for page_number in soup.find_all("span", class_="pagenum"):
            page_number.decompose()
        for br in soup.find_all("br"):
            br.replace_with(LINE_BREAK)
        stories, errors = {}, {}
        for anchor in anchors:
            try:
                stories[anchor] = story_paragraphs(soup, anchor)
            except StoryFetchError as e:
                errors[anchor] = str(e)
        return stories, errors
    finally:
        del soup
        gc.collect()


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
        self._init_story_cache()
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

    def _init_story_cache(self, directory=None):
        """Where fetched story text is kept - see StoryCache."""
        self._story_cache = StoryCache(
            directory or os.path.join(get_xdg_cache_save_path(), "skills", self.skill_id), self.log)
        self._fetch_lock = threading.Lock()
        # a book URL, or 'URL#anchor' for a story its page did not yield
        # -> (time.monotonic() of the failure, what failed)
        self._failures = {}

    def _check_backoff(self, key):
        failure = self._failures.get(key)
        if failure is None:
            return
        when, what = failure
        wait = FAILURE_BACKOFF - (time.monotonic() - when)
        if wait > 0:
            raise StoryFetchError(f"{what} (not trying again for {int(wait)} s)")
        del self._failures[key]

    def _download(self, url, last_modified=None):
        """(the page's bytes, its Last-Modified), or (None, last_modified)
        when it has not changed since last_modified."""
        headers = {"User-Agent": USER_AGENT}
        if last_modified:
            headers["If-Modified-Since"] = last_modified
        try:
            r = requests.get(url, headers=headers, timeout=FETCH_TIMEOUT)
            if r.status_code == 304 and last_modified:
                return None, last_modified
            r.raise_for_status()
        except requests.RequestException as e:
            raise StoryFetchError(f"failed to fetch {url}: {e}") from e
        return r.content, r.headers.get("Last-Modified")

    def _fetch_book(self, url, anchor, stale=None):
        """Fetch one book and cache every story of it in the index (and
        the one at `anchor`). Given a stale cached story, ask with its
        Last-Modified: a 304 renews every story cached from that same
        page, and nothing is downloaded."""
        self._check_backoff(url)
        last_modified = stale.get("last_modified") if stale else None
        try:
            content, last_modified = self._download(url, last_modified)
        except StoryFetchError as e:
            self._failures[url] = (time.monotonic(), str(e))
            raise
        now = time.time()
        anchors = [e["anchor"] for e in self.index.values() if e["url"] == url]
        if anchor not in anchors:
            anchors.append(anchor)
        if content is None:
            renewed = (self._story_cache.get(url, a) for a in anchors)
            self._story_cache.put([dict(r, fetched_at=now) for r in renewed
                                   if r and r.get("last_modified") == last_modified])
            return
        stories, errors = extract_book(content, anchors)
        self._story_cache.put([
            {"format": CACHE_FORMAT, "url": url, "anchor": a, "fetched_at": now,
             "last_modified": last_modified, "paragraphs": paragraphs}
            for a, paragraphs in stories.items()])
        for a, error in errors.items():
            self.log.error(f"{url}#{a}: {error}")
            self._failures[f"{url}#{a}"] = (time.monotonic(), f"{error} in {url}")

    def get_story_paragraphs(self, entry):
        """A story's paragraphs: from the cache when it has them, else by
        fetching the story's book - once for all the stories in it, see
        extract_book(). A copy cached longer ago than CACHE_MAX_AGE is
        still read when the book cannot be fetched again."""
        url, anchor = entry["url"], entry["anchor"]
        record = self._story_cache.get(url, anchor)
        if record and self._story_cache.is_fresh(record):
            return record["paragraphs"]
        with self._fetch_lock:
            # a request for another story of the same book may have
            # fetched it while this one waited
            record = self._story_cache.get(url, anchor)
            if record and self._story_cache.is_fresh(record):
                return record["paragraphs"]
            try:
                self._check_backoff(f"{url}#{anchor}")
                self._fetch_book(url, anchor, record)
            except StoryFetchError as e:
                if record:
                    self.log.warning(f"{e} - reading the copy cached {time.ctime(record['fetched_at'])}")
                    return record["paragraphs"]
                raise
            record = self._story_cache.get(url, anchor)
        if record is None:
            failure = self._failures.get(f"{url}#{anchor}")
            raise StoryFetchError(failure[1] if failure else f"no story text at {url}#{anchor}")
        return record["paragraphs"]

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
