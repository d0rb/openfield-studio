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

# Taking someone's clothes off, or seeing through them, is refused whatever the words around it: an edit can be aimed at
# a real person's photo, and a Direct subject can start from one. A garment, not a hat or a jacket, is what is meant.
GARMENT = (r"clothes|clothing|garments?|shirts?|t-?shirts?|blouses?|dress(?:es)?|skirts?|trousers|jeans|underwear|bras?|"
           r"panties|knickers|briefs|boxers|bikinis?|swimsuits?|leggings|tights|bathrobes?|(?:tank|crop|halter|tube)\s+tops?")
# garments only as someone's own ("her top", "his wet towel"): a top hat, the towel over the dough, a dog that pants
WORN = r"tops?|towels?|robes?|pants|shorts"
_OWN = r"his|her|their|my|your"
WORD = r"(?!(?:from|of|off|on|onto|in|into|with|for|to|at|by|over|under)\b)[\w'’-]+\s+"  # a word before a garment, never a preposition
# a top hat, the top of a jar, dress shoes, a dress taken from a mannequin: the garment word names something else
_ELSEWHERE = (r"(?!\s+(?:hats?|caps?|of|codes?|shoes?|boots?|pegs?|lines?|hangers?|racks?|rails?|pins?|buttons?|pockets?|tags?|"
              r"labels?|shops?|sizes?)\b|\s+(?:off\s+)?from\s+(?:the|a|an)\s+(?:mannequins?|dumm(?:y|ies)|hangers?|racks?|rails?|"
              r"hooks?|pegs?|(?:washing\s+|clothes)?lines?|shel(?:f|ves)|wardrobes?|closets?|drawers?|suitcases?|bags?|box(?:es)?|"
              r"baskets?|dryers?|washers?|washing\s+machines?|chairs?|beds?|floor|table|counter|window)\b)")
_WORN_BY = (rf"(?:(?:(?:{_OWN}|the|its|all|any|of)\s+){{0,2}}(?:{WORD}){{0,2}}(?:{GARMENT})|"
            rf"(?:{_OWN})\s+(?:{WORD})?(?:{WORN}))\b{_ELSEWHERE}")
_FALLS = r"(?:fall(?:s|en|ing)?|fell|drop(?:s|ped|ping)?|slid(?:e|es|ing)?|slip(?:s|ped|ping)?)"
_UNDRESS = [re.compile(p, re.IGNORECASE) for p in (
    rf"\b(?:remov(?:e[sd]?|ing)|tak(?:e[sn]?|ing)\s+off|took\s+off|strip(?:s|ped|ping)?(?:\s+off)?|shed(?:s|ding)?|"
    rf"(?:pull(?:s|ed|ing)?|peel(?:s|ed|ing)?|slip(?:s|ped|ping)?|shrug(?:s|ged|ging)?)\s+off|without|minus|los(?:e|ing)|"
    rf"erase|delete|(?:slip(?:s|ped|ping)?|wriggl(?:e[sd]?|ing)|wiggl(?:e[sd]?|ing)|shimm(?:y|ies|ied|ying)|"
    rf"step(?:s|ped|ping)?)\s+out\s+of)\s+{_WORN_BY}",
    # "her dress falls to the floor", "the dress slides off her shoulders", "she lets her robe drop"
    rf"\b(?:(?:{_OWN})\s+(?:{WORD})?(?:{GARMENT}|{WORN})|the\s+(?:{WORD})?(?:{GARMENT}))\s+{_FALLS}\s+"
    rf"(?:off|down|away|to\s+(?:the\s+)?(?:floor|ground))\b",
    rf"\blet(?:s|ting)?\s+(?:{_OWN})\s+(?:{WORD})?(?:{GARMENT}|{WORN})\s+(?:fall|drop|slide|slip)\b",
    rf"\bun(?:button|zip|hook|tie|lace)\w*\s+{_WORN_BY}[^.!?]{{0,40}}?\blet(?:s|ting)?\s+(?:it|them)\s+(?:fall|drop|slide|slip)\b",
    r"\b(?:in|wearing|dressed\s+in|with)\s+(?:only\s+|just\s+)?nothing(?:\s+on)?\b",
    r"\b(?:has|had|have|having)\s+nothing\s+on\b",
    rf"\b(?:see[- ]through|sheer|transparent)\s+(?:{WORD}){{0,2}}(?:{GARMENT}|lingerie)\b{_ELSEWHERE}",
    rf"\bsee[- ]through\s+(?:{WORN})\b{_ELSEWHERE}",
)]
UNDRESS_REASON = "removing or seeing through someone's clothes"

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
    if any(p.search(cleaned) for p in _UNDRESS):
        return MESSAGE.format(reason=UNDRESS_REASON)
    return None


def require_safe(*texts: str | None) -> None:
    """Raise ValueError (a 422 over HTTP) naming the problem when any text is refused."""
    for text in texts:
        if text and (message := check_prompt(text)):
            raise ValueError(message)
