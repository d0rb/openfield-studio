"""A plain content guard for prompts: the app is for lawful, safe-for-work footage.

This is a good-faith filter, not a moderation system. It refuses prompts that ask for explicit sexual
content, graphic gore or self-harm before anything is sent to a model, with a reason a person can act
on. It cannot recognise a real person's name; the interface and the receipts say that characters must
be invented or consented to, and every output is marked AI-generated.
"""
from __future__ import annotations

import re

_BLOCKED = {
    "sexual content": (
        r"nude|nudes|naked(?!\s+eye)|nsfw|porn\w*|erotic\w*|explicit|topless|nipples?|genitals?|vagina|penis|"
        r"sex|sexy|sexual\w*|fetish\w*|bdsm|lingerie|undress\w*|strip ?tease|stripper|orgasm|"
        r"cum|masturbat\w*|seductive(?:ly)? undress\w*"
    ),
    "graphic violence": r"gore|gory|dismember\w*|beheading|decapitat\w*|mutilat\w*|torture|disembowel\w*",
    "self-harm": r"suicide|self[- ]harm|slit (?:my|his|her|their) wrists",
}
_PATTERNS = {reason: re.compile(rf"\b(?:{words})\b", re.IGNORECASE) for reason, words in _BLOCKED.items()}

# Everyday phrases that contain a blocked word but mean something else. They are blanked out before the
# check, so "a Gore-Tex jacket in nude lipstick, cum laude" is not refused while the bare words still are.
_BENIGN = re.compile(
    r"\b(?:gore[- ]?tex|nude\s+(?:lip\w*|shade\w*|colou?r\w*|beige|polish|makeup|tones?)|"
    r"(?:(?:magna|summa)\s+)?cum\s+laude|naked[- ]eye)\b",
    re.IGNORECASE,
)

MESSAGE = ("This studio makes lawful, safe-for-work footage, so it can't use that description "
           "({reason}). Describe a different scene or character.")


def check_prompt(text: str) -> str | None:
    """A refusal message when the text asks for something the studio does not make, else None."""
    cleaned = _BENIGN.sub(" ", text or "")
    for reason, pattern in _PATTERNS.items():
        if pattern.search(cleaned):
            return MESSAGE.format(reason=reason)
    return None


def require_safe(*texts: str | None) -> None:
    """Raise ValueError (a 422 over HTTP) naming the problem when any text is refused."""
    for text in texts:
        if text and (message := check_prompt(text)):
            raise ValueError(message)
