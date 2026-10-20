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
