"""ovos.common_reading.vocabulary: what this provider tells the pipeline it
can read. Since pipeline 0.3.0 a request only reaches a provider whose
words (a kind of text, a collection or a title) it names."""
from ovos_bus_client.message import Message


def _sent(skill):
    return [c.args[0] for c in skill.bus.emit.call_args_list
            if c.args[0].msg_type == "ovos.common_reading.vocabulary"]


def test_vocabulary_is_collection_names_and_titles(skill):
    skill.index = {"A STORY": {}, "ANOTHER": {}}
    vocab = skill._vocabulary(sorted(skill.served)[0])
    assert vocab["collections"] and all(isinstance(c, str) for c in vocab["collections"])
    assert sorted(vocab["titles"]) == ["A STORY", "ANOTHER"]


def test_announced_for_the_language_served_and_on_request(skill):
    skill.index = {"A STORY": {}}
    skill._announce_vocabulary()
    assert [m.data["lang"] for m in _sent(skill)] == sorted(skill.served)
    skill.bus.emit.reset_mock()
    skill.handle_vocabulary_get(Message("ovos.common_reading.vocabulary.get", {"langs": ["xx-XX"]}))
    assert _sent(skill) == []
