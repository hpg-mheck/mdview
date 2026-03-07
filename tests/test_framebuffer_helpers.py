"""Regression tests for framebuffer helper utilities."""

import pytest

from tests.helpers.framebuffer import TextFramebuffer


def test_peek_reads_viewport_coordinates() -> None:
    framebuffer = TextFramebuffer("AB\ncd", width=4, height=3)

    assert framebuffer.peek(0, 0) == "A"
    assert framebuffer.peek(1, 0) == "B"
    assert framebuffer.peek(0, 1) == "c"
    assert framebuffer.peek(3, 2) == " "
    assert framebuffer.peek(0, 4, default="?") == "?"


def test_poke_updates_the_viewport() -> None:
    framebuffer = TextFramebuffer("hi", width=4, height=2)

    framebuffer.poke(2, 0, "X")
    framebuffer.poke(1, 1, "Y")

    assert framebuffer.peek(2, 0) == "X"
    assert framebuffer.peek(1, 1) == "Y"

    framebuffer.poke(5, 5, "Z")
    assert framebuffer.peek(1, 1) == "Y"


def test_poke_rejects_multi_character_values() -> None:
    framebuffer = TextFramebuffer("text", width=4, height=1)

    with pytest.raises(ValueError):
        framebuffer.poke(0, 0, "NO")
