"""Every prompt and schema: moments, translation, layer, caption, script."""
from pydantic import BaseModel, Field

from pages import llm
from pages.llm import LLMError

RESTRICTED = ("Restricted topics: list any of these in `flags` if the material touches them: exaggerated "
              "health claims, cosmetic procedures, get rich schemes, miracle or astrology claims. "
              "Never make such claims yourself.")


# --- Moments (adapted from musubi-clips SKILL.md §2) ---

class HookParts(BaseModel):
    kicker: str
    big: str
    punch: str


class Moment(BaseModel):
    start: float
    end: float
    title: str
    hook_text: str
    hook_parts: HookParts | None
    reason: str
    emphasis: list[str]
    focus_x: float | None
    speaker_name: str | None
    speaker_role: str | None
    hook: int = Field(ge=1, le=5)
    standalone: int = Field(ge=1, le=5)
    payoff: int = Field(ge=1, le=5)
    emotion: int = Field(ge=1, le=5)


class Moments(BaseModel):
    moments: list[Moment]


PICK_RULES = """\
Each transcript line is `[start-end seconds] text`. Choose clip moments for a short vertical reel.

What makes a moment worth posting:
- It stands alone. Someone who never saw the video has to follow it. No "as I said", no unexplained "he" or "that".
- It hooks inside 3 seconds. Start on the first word of a line that makes someone stop scrolling: a bold claim, a number, a question, a confession.
- It pays off. End right after the punchline or the answer, never mid thought.
- It stays on the hook's topic to the last word. Read the next two lines after your end: if they are a new question, a host moving on, or another speaker reacting, end before them.
- Every speaker finishes. Start on the first word of a sentence and end on its last; never open on a word like "she" or "that" that needs the line before it.
- Length is 30 to 90 seconds.
- Moments never overlap.
- Skip any span with music, a song or a "[Music]" tag.
- Timestamps come from the transcript lines; a line's start and end are safe choices.

For each moment write:
- hook_text: at most 8 words on screen for the first seconds, in English. No emojis, hashtags or dashes.
- hook_parts: the same hook split for the animation: kicker (a short line above), big (one number or short word that slams in, such as 90% or ₹5 Cr), punch (one to three words). Any part may be "". Use null to let the hook_text be split automatically.
- title: a short working title. reason: one sentence on why it holds a viewer.
- emphasis: 3 to 8 words from the moment's own speech to punch (names, places, numbers, the words the point turns on), in English as the English captions will show them.
- focus_x: where the speaker sits across the frame, 0 left to 1 right, for a two shot; null when one person fills the frame.
- speaker_name and speaker_role: who is talking, from the video title, the intro or someone addressing them by name. Null if unsure or if several people talk.
- Scores from 1 to 5: hook (first 3 seconds stop the scroll), standalone (needs no context), payoff (ends on a satisfying line), emotion (funny, surprising, controversial or moving). Be strict: most land at 2 to 4, and 5 is rare.
"""


def pick_moments(transcript: str, title: str, want: int) -> list[Moment]:
    prompt = (f"{PICK_RULES}\nPick {want * 2} candidates; the best {want} will be kept.\n\n"
              f"Video title: {title}\n\nTranscript:\n{transcript}")
    return llm.ask(prompt, Moments).moments


# --- Translation (adapted from SKILL.md §4) ---

class Line(BaseModel):
    start: float
    end: float
    text: str


class Lines(BaseModel):
    lines: list[Line]


def translate(sentences: list[str]) -> list[dict]:
    prompt = ("Translate these timed sentences into English captions, one English line per sentence. "
              "Each is `[start-end] text`. Copy each start and end exactly. Translate by meaning, the way a "
              "subtitler would, not word by word. Keep names, brands and numbers as spoken (Darling, ₹10,000, "
              "35 years). End every line with a full stop or question mark.\n\n" + "\n".join(sentences))
    return [line.model_dump() for line in llm.ask(prompt, Lines).lines]


# --- Original layer ---

class Card(BaseModel):
    at: float
    title: str
    body: str


class Layer(BaseModel):
    intro: str
    takeaway: str
    cards: list[Card]
    flags: list[str]


def write_layer(page, moment: Moment, text: str) -> Layer:
    prompt = (f"You write the original layer for a reel on the Instagram page @{page.handle} "
              f"(topics: {', '.join(page.topics)}), in the page's voice, in English.\n"
              "- intro: a voiceover of 8 to 16 words that sets up the clip.\n"
              "- takeaway: a voiceover of 6 to 10 words that closes it.\n"
              f"- cards: 1 to 3 context cards with facts the clip does not say. Each `at` is in source seconds "
              f"between {moment.start} and {moment.end}. title short, body one sentence.\n"
              f"- flags: {RESTRICTED}\n\n"
              f"Clip title: {moment.title}\nWhat the clip says:\n{text}")
    layer = llm.ask(prompt, Layer)
    if not 1 <= len(layer.cards) <= 3:
        raise ValueError(f"layer needs 1 to 3 cards, got {len(layer.cards)}")
    for card in layer.cards:
        if not moment.start <= card.at <= moment.end:
            raise ValueError(f"card at {card.at} outside {moment.start}-{moment.end}")
    return layer


# --- Caption ---

class CaptionDraft(BaseModel):
    text: str
    hashtags: list[str]


def _hashtags(tags: list[str]) -> list[str]:
    out = []
    for t in tags:
        t = "#" + "".join(t.split()).lstrip("#")
        if t != "#" and t not in out:
            out.append(t)
    return out[:5]


def write_caption(page, about: str, credits: list[str], previous: list[str]) -> str:
    prompt = (f"Write an Instagram caption in English for a reel on @{page.handle} (topics: {', '.join(page.topics)}). "
              "Open with a line that makes people read on, use the keywords someone would search for, "
              "keep it short, no hashtags in the text. Then give up to 5 relevant hashtags. "
              "Never make exaggerated health claims, cosmetic procedure claims, get rich promises, "
              "or miracle or astrology claims.\n\n"
              f"The reel: {about}")
    for attempt in range(2):
        draft = llm.ask(prompt, CaptionDraft)
        tail = "\n\n" + "\n".join(credits) + "\n\n" + " ".join(_hashtags(draft.hashtags))
        caption = draft.text.strip()[:2200 - len(tail)] + tail
        if caption not in previous:
            return caption
        prompt += "\n\nThat caption was already used. Write a different one."
    raise LLMError("caption repeats a previous one")


# --- Script first reels ---

class Beat(BaseModel):
    line: str
    shot_query: str


class Script(BaseModel):
    idea: str
    title: str
    hook_text: str
    beats: list[Beat]
    claims: list[str]
    flags: list[str]


def write_script(page, used_ideas: list[str]) -> Script:
    used = "\n".join(f"- {i}" for i in used_ideas) or "- none yet"
    prompt = (f"Write a voiceover script for a reel on the Instagram page @{page.handle} "
              f"(topics: {', '.join(page.topics)}), in English.\n"
              "- Pick a fresh idea, not one of these used ideas:\n" + used + "\n"
              "- 20 to 45 seconds when spoken, about 55 to 110 words.\n"
              "- 5 to 7 beats. The first beat is the hook line, the last is the closing line. Each beat has the "
              "spoken line and a shot_query: a short stock footage search for what is on screen.\n"
              "- hook_text: at most 8 words on screen, no emojis, hashtags or dashes.\n"
              "- Every factual claim must be checkable; list each one in `claims`.\n"
              f"- flags: {RESTRICTED}")
    script = llm.ask(prompt, Script)
    if not 5 <= len(script.beats) <= 7:
        raise ValueError(f"script needs 5 to 7 beats, got {len(script.beats)}")
    if len(script.hook_text.split()) > 8:
        raise ValueError("hook_text over 8 words")
    return script
