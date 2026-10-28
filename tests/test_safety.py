from __future__ import annotations

import pytest

from openfield.engine.safety import check_prompt, require_safe


@pytest.mark.parametrize("text", [
    "A lighthouse at dusk, waves breaking on the rocks",
    "A courier in a yellow raincoat pushing a bicycle through a night market",
    "Essex and Sussex in autumn, the Perseid meteor shower visible to the naked eye",  # whole words only
    "a bowl of cumin and a Vegas-style neon sign",
    "a hiker in a Gore-Tex jacket and Gore Tex boots",
    "a model wearing nude lipstick and a nude beige coat",
    "she graduated magna cum laude",
    "visible to the naked-eye and the naked eye alike",
])
def test_ordinary_prompts_pass_whole_word_matching(text):
    assert check_prompt(text) is None


@pytest.mark.parametrize("text, reason", [
    ("a nude woman on a beach", "sexual content"),
    ("NSFW closeup", "sexual content"),
    ("two people having sex", "sexual content"),
    ("a model in lingerie", "sexual content"),
    ("gory dismemberment scene", "graphic violence"),
    ("a man planning suicide", "self-harm"),
    # an allowed phrase never shields a blocked word beside it
    ("a Gore-Tex jacket and a nude figure", "sexual content"),
    ("cum laude, then explicit content", "sexual content"),
    ("gory scene, naked-eye view", "graphic violence"),
])
def test_explicit_prompts_are_refused_with_a_reason(text, reason):
    message = check_prompt(text)
    assert message and reason in message and "safe-for-work" in message


def test_empty_and_missing_text_is_not_a_violation():
    assert check_prompt("") is None
    assert check_prompt(None) is None


def test_require_safe_raises_on_the_first_bad_text_and_ignores_none():
    require_safe("a lighthouse", None, "")
    with pytest.raises(ValueError, match="sexual content"):
        require_safe("a lighthouse", "nude figure drawing")


@pytest.mark.parametrize("text", [
    "Remove her clothes from the picture",
    "take off his shirt and trousers",
    "Remove her bikini top",
    "Dress the person in nothing",
    "the same person without clothes",
    "a woman with nothing on",
    "she has nothing on",
    "a man in a see-through shirt",
    "strip off her dress",
    # the common phrasings, which a What happens field invites
    "She slips out of her dress",
    "He sheds his clothes",
    "She lets her robe drop to the floor",
    "Her dress falls to the floor",
    "She wriggles out of her jeans",
    "He unbuttons his shirt and lets it fall",
    # a top, a towel, a robe, pants and shorts are garments as someone's own, with a word for them or not
    "She removes her towel",
    "takes off his top and bows",
    "She takes off her silk robe",
    "He pulls off his gym shorts",
    "the dress slides off her shoulders",
    "Remove the woman's dress",
    "a woman in a see-through top",
])
def test_undressing_is_refused_with_a_reason(text):
    message = check_prompt(text)
    assert message and "clothes" in message


@pytest.mark.parametrize("text", [
    "Remove the boat from the picture",
    "Remove the fishing net from the picture",
    "take off his hat",
    "a man without a jacket in the rain",
    "Dress the person in a red wool coat",
    "a woman in a white summer dress walks through poppies",
    "Remove the dragon from the picture",
    "nothing on the horizon but the sea",
    # a garment word naming something else, or a garment that nobody is wearing
    "A magician takes off his top hat and bows",
    "She removes the top of the jar",
    "The bartender removes the bottle tops",
    "A baker removes the towel from the rising dough",
    "A seamstress removes the dress from the mannequin",
    "A ghost in transparent robes",
    "A climber clings to a sheer cliff top",
    "A dog without a leash pants in the summer heat",
    "the detergent removes stains from shirts",
    "a party without a dress code",
    "a bride in a lace dress that falls to the floor",
    "He steps out of the dress shop",
    "The tree sheds its leaves",
    "His hat falls off in the wind",
])
def test_ordinary_edits_and_scenes_still_pass(text):
    assert check_prompt(text) is None, text
