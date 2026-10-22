from types import SimpleNamespace

import pytest

from pages import llm, writing

PAGE = SimpleNamespace(handle="podcastbawaal", topics=["startups", "founders"])
BILLI = SimpleNamespace(handle="tech_bawaal", topics=["cats"])


def M(start=100.0, end=150.0):
    return writing.Moment(start=start, end=end, title="t", hook_text="h", hook_parts=None, reason="r",
                          emphasis=[], focus_x=None, speaker_name=None, speaker_role=None,
                          hook=3, standalone=3, payoff=3, emotion=3)


def test_pick_moments_prompt_has_rules(monkeypatch):
    seen = {}
    monkeypatch.setattr(llm, "ask", lambda p, s: (seen.setdefault("p", p), s(moments=[M()]))[1])
    got = writing.pick_moments("[1.0-5.0] hi", "Ep 1", 2)
    assert got[0].start == 100.0
    p = seen["p"]
    assert "15 to 30 seconds" in p and "3 different hooks" in p and "[Music]" in p and "[1.0-5.0] hi" in p and "Ep 1" in p and "4 candidates" in p


def test_pick_prompt_carries_the_scoring_and_hook_rules(monkeypatch):
    seen = {}
    monkeypatch.setattr(llm, "ask", lambda p, s: (seen.setdefault("p", p), s(moments=[M()]))[1])
    writing.pick_moments("[1.0-5.0] hi", "Ep 1", 2, topics="tech and AI")
    p = seen["p"]
    for rule in ("controversy 30%", "insight 35%", "engagement 20%", "topic_match 15%", "Page topics: tech and AI",
                 "curiosity gap", "Never a summary or a label", "No emojis, hashtags or dashes", "cold_open_start",
                 "2 to 5 second"):
        assert rule in p
    assert {"controversy", "insight", "engagement", "topic_match", "cold_open_start", "cold_open_end"} <= set(M().model_dump())


def test_translate_returns_dicts(monkeypatch):
    seen = {}
    monkeypatch.setattr(llm, "ask", lambda p, s: (seen.setdefault("p", p), s(lines=[writing.Line(start=1.0, end=2.0, text="Hi.")]))[1])
    assert writing.translate(["[1.0-2.0] namaste"]) == [{"start": 1.0, "end": 2.0, "text": "Hi."}]
    assert "[1.0-2.0] namaste" in seen["p"]


def layer(*ats):
    return writing.Layer(cards=[writing.Card(at=a, title="c", body="b") for a in ats], flags=[])


def test_layer_validates_cards(monkeypatch):
    monkeypatch.setattr(llm, "ask", lambda p, s: layer(120.0))
    assert writing.write_layer(PAGE, M(), "text").cards[0].at == 120.0
    for bad in (layer(200.0), layer(), layer(110, 120, 130, 140)):
        monkeypatch.setattr(llm, "ask", lambda p, s, bad=bad: bad)
        with pytest.raises(ValueError):
            writing.write_layer(PAGE, M(), "text")


def test_caption_caps_hashtags_and_appends_credits(monkeypatch):
    monkeypatch.setattr(llm, "ask", lambda p, s: s(text="Why founders burn out", hashtags=["a", "#b", "c", "d", "e", "f", "g"]))
    cap = writing.write_caption(PAGE, "burnout clip", ["🎙️ Ep 12 via @pod"], previous=[])
    assert cap.count("#") == 5 and "🎙️ Ep 12 via @pod" in cap and len(cap) <= 2200
    assert cap == "Why founders burn out\n\n🎙️ Ep 12 via @pod\n\n#a #b #c #d #e"


def test_caption_normalises_hashtags(monkeypatch):
    monkeypatch.setattr(llm, "ask", lambda p, s: s(text="t", hashtags=[" ##cat life ", "catlife", "#dogs"]))
    assert writing.write_caption(PAGE, "a", [], previous=[]).endswith("#catlife #dogs")


def test_caption_shortens_to_2200(monkeypatch):
    monkeypatch.setattr(llm, "ask", lambda p, s: s(text="x" * 3000, hashtags=["a"]))
    assert len(writing.write_caption(PAGE, "a", ["c"], previous=[])) == 2200


def test_caption_cuts_at_word_boundary(monkeypatch):
    monkeypatch.setattr(llm, "ask", lambda p, s: s(text="hello " * 500, hashtags=["a"]))
    cap = writing.write_caption(PAGE, "a", ["c"], previous=[])
    body = cap.split("\n\n")[0]
    assert len(cap) <= 2200 and body.endswith("hello") and set(body.split()) == {"hello"}


def test_flags_prompt_says_empty_unless_restricted(monkeypatch):
    seen = []
    monkeypatch.setattr(llm, "ask", lambda p, s: (seen.append(p), layer(120.0) if s is writing.Layer else SCRIPT_WITH_4_BEATS)[1])
    writing.write_layer(PAGE, M(), "text")
    with pytest.raises(ValueError):
        writing.write_script(BILLI, [])
    for p in seen:
        assert "flags is an EMPTY list unless" in p and "Each flag names which one" in p


def test_caption_never_repeats(monkeypatch):
    monkeypatch.setattr(llm, "ask", lambda p, s: s(text="same", hashtags=["a"]))
    prev = writing.write_caption(PAGE, "a", ["c"], previous=[])
    with pytest.raises(llm.LLMError):
        writing.write_caption(PAGE, "a", ["c"], previous=[prev])


SCRIPT_WITH_4_BEATS = writing.Script(idea="i", title="t", hook_text="h", beats=[writing.Beat(line="l", shot_query="q")] * 4, claims=[], flags=[])


def test_script_prompt_lists_used_ideas_and_validates_beats(monkeypatch):
    seen = {}
    monkeypatch.setattr(llm, "ask", lambda p, s: (seen.setdefault("p", p), SCRIPT_WITH_4_BEATS)[1])
    with pytest.raises(ValueError, match="5 to 7 beats"):
        writing.write_script(BILLI, ["why cats knead"])
    assert "why cats knead" in seen["p"] and "tech_bawaal" in seen["p"] and "cats" in seen["p"]


def test_topics_string_used_verbatim(monkeypatch):
    topics = "cats, dogs, wild animals and nature: funny facts"
    page = SimpleNamespace(handle="tech_bawaal", topics=topics)
    seen = []
    monkeypatch.setattr(llm, "ask", lambda p, s: (seen.append(p), {writing.Layer: layer(120.0), writing.Script: SCRIPT_WITH_4_BEATS}.get(s) or s(text="t", hashtags=[]))[1])
    writing.write_layer(page, M(), "text")
    writing.write_caption(page, "a", [], previous=[])
    with pytest.raises(ValueError):
        writing.write_script(page, [])
    assert len(seen) == 3 and all(topics in p for p in seen)


def test_script_hook_over_8_words(monkeypatch):
    s = SCRIPT_WITH_4_BEATS.model_copy(update={"beats": SCRIPT_WITH_4_BEATS.beats[:3] * 2, "hook_text": "one two three four five six seven eight nine"})
    monkeypatch.setattr(llm, "ask", lambda p, sc: s)
    with pytest.raises(ValueError, match="hook_text over 8 words"):
        writing.write_script(BILLI, [])
