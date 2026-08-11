"""Tests for generate_image routing — real vs imaginary subject guards."""

from __future__ import annotations

from arka.generate.image import (
    is_real_world_subject,
    is_search_or_research_intent,
    nl_to_argv,
    should_generate_image,
)
from arka.routing.symbolic import route_generate_image


def test_nl_to_argv_allows_creative_subjects():
    assert nl_to_argv("generate image of a cyberpunk city at sunset") == [
        "a cyberpunk city at sunset"
    ]
    assert nl_to_argv("draw a fantasy dragon in watercolor style") == [
        "fantasy dragon in watercolor style"
    ]
    assert nl_to_argv("create illustration of a magical forest") == ["a magical forest"]


def test_nl_to_argv_blocks_real_world_subjects():
    assert nl_to_argv("generate image of Indian Pariah dog") == []
    assert nl_to_argv("create picture of Rajapalayam hound breed") == []
    assert nl_to_argv("draw a photo of Taj Mahal") == []
    assert route_generate_image("generate image of Mudhol Hound") is None


def test_nl_to_argv_blocks_search_and_research():
    assert nl_to_argv("search for Indian native dog breeds with images") == []
    assert nl_to_argv("research local dog species in India") == []
    assert nl_to_argv("tell me about Kombai dog breed") == []
    assert nl_to_argv("build a website about Indian dogs with images") == []
    assert nl_to_argv("find photos of Himalayan Gaddi dog") == []


def test_nl_to_argv_allows_stylized_real_subjects():
    assert nl_to_argv("generate artistic illustration of a fantasy Indian temple") == [
        "artistic illustration of a fantasy Indian temple"
    ]
    assert nl_to_argv("create cartoon image of a space cat") == ["cartoon image of a space cat"]


def test_should_generate_image_helpers():
    assert is_search_or_research_intent("search for dog breeds in India")
    assert is_real_world_subject("Indian Pariah street dog")
    assert not is_real_world_subject("cyberpunk neon alley")
    assert should_generate_image("generate image of a futuristic robot city")
    assert not should_generate_image("generate image of Indian Pariah dog")


def test_nl_to_argv_still_allows_generic_prompts():
    assert nl_to_argv("generate image of a sunset over the ocean") == [
        "a sunset over the ocean"
    ]
