from __future__ import annotations

import re
from dataclasses import dataclass

from intent_contracts.enums import Action, TargetReference

# STOP and CANCEL are matched before every other intent.
STOP_PHRASES = (
    "emergency stop",
    "full stop",
    "stop",
    "halt",
    "freeze",
)
CANCEL_PHRASES = (
    "never mind",
    "nevermind",
    "don't do that",
    "dont do that",
    "do not do that",
    "scratch that",
    "forget it",
    "no thanks",
    "undo that",
    "cancel",
    "abort",
    "nope",
)
HANDOFF_PHRASES = (
    "give me",
    "hand me",
    "pass me",
    "bring me",
    "get me",
    "can i have",
    "let me have",
    "i would like",
    "i'd like",
    "i want",
    "i need",
    "hand off",
    "handoff",
    "hand over",
    "give it",
    "pass it",
    "fetch",
    "bring",
    "grab",
    "give",
    "pass",
    "get",
)
SELECT_PHRASES = (
    "point to",
    "point at",
    "select",
    "choose",
    "pick",
    "take",
    "highlight",
)
CONFIRM_PHRASES = (
    "that's right",
    "thats right",
    "sounds good",
    "go ahead",
    "go for it",
    "yes please",
    "affirmative",
    "confirm",
    "proceed",
    "do it",
    "okay",
    "yeah",
    "yep",
    "yes",
    "sure",
    "ok",
)
COLOR_TO_OBJECT = {
    "blue": "object_blue_1",
    "red": "object_red_1",
    "green": "object_green_1",
    "yellow": "object_yellow_1",
}
ORDINAL_PATTERNS = (
    (re.compile(r"\b(first|1st)\b"), "first"),
    (re.compile(r"\b(second|2nd)\b"), "second"),
    (re.compile(r"\b(third|3rd)\b"), "third"),
    (re.compile(r"\b(fourth|4th)\b"), "fourth"),
)
DEICTIC_RE = re.compile(r"\b(that one|this one|those|these|that|this)\b")


@dataclass(frozen=True)
class ParseResult:
    action: str
    target_reference: str
    target_object_id: str | None
    confidence: float
    grammar_match: float


def normalize_transcript(text: str) -> str:
    lowered = text.lower().strip()
    lowered = lowered.replace("’", "'").replace("‘", "'").replace("`", "'")
    lowered = re.sub(r"[^a-z0-9'\s]", " ", lowered)
    return re.sub(r"\s+", " ", lowered).strip()


def _contains_phrase(text: str, phrase: str) -> bool:
    return bool(re.search(rf"(?<![a-z0-9']){re.escape(phrase)}(?![a-z0-9'])", text))


def _first_phrase(text: str, phrases: tuple[str, ...]) -> str | None:
    for phrase in phrases:
        if _contains_phrase(text, phrase):
            return phrase
    return None


def parse_utterance(transcript: str, *, asr_confidence: float | None = None) -> ParseResult:
    text = normalize_transcript(transcript)
    if not text:
        return _finished("UNKNOWN", TargetReference.NONE, None, 0.1, asr_confidence)

    if _first_phrase(text, STOP_PHRASES):
        return _finished(Action.STOP, TargetReference.NONE, None, 0.99, asr_confidence)
    if _first_phrase(text, CANCEL_PHRASES):
        return _finished(Action.CANCEL, TargetReference.NONE, None, 0.99, asr_confidence)

    action: str | None = None
    grammar = 0.4
    if _first_phrase(text, HANDOFF_PHRASES):
        action = Action.REQUEST_HANDOFF
        grammar = 0.9
    elif _first_phrase(text, SELECT_PHRASES):
        action = Action.SELECT_OBJECT
        grammar = 0.9
    elif _first_phrase(text, CONFIRM_PHRASES):
        action = Action.CONFIRM
        grammar = 0.85

    target_reference: str = TargetReference.NONE
    target_object_id: str | None = None
    for color, object_id in COLOR_TO_OBJECT.items():
        if re.search(rf"\b{color}\b", text):
            target_reference = TargetReference.NAMED
            target_object_id = object_id
            grammar = max(grammar, 0.88)
            break
    if target_object_id is None:
        for pattern, _name in ORDINAL_PATTERNS:
            if pattern.search(text):
                target_reference = TargetReference.ORDINAL
                grammar = max(grammar, 0.7)
                break
    if (
        target_object_id is None
        and target_reference == TargetReference.NONE
        and DEICTIC_RE.search(text)
    ):
        target_reference = TargetReference.DEICTIC
        grammar = max(grammar, 0.8)

    if action is None:
        return _finished("UNKNOWN", target_reference, target_object_id, 0.1, asr_confidence)
    return _finished(action, target_reference, target_object_id, grammar, asr_confidence)


def _finished(
    action: str,
    target_reference: str,
    target_object_id: str | None,
    grammar_match: float,
    asr_confidence: float | None,
) -> ParseResult:
    acoustic = 0.7 if asr_confidence is None else asr_confidence
    confidence = max(0.0, min(1.0, 0.5 * grammar_match + 0.5 * acoustic))
    if action in {Action.STOP, Action.CANCEL}:
        confidence = max(confidence, 0.95)
    return ParseResult(
        str(action), str(target_reference), target_object_id, confidence, grammar_match
    )
