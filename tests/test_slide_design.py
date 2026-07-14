"""Tests for slide_design tokens — contrast, spacing, traction detection."""

from __future__ import annotations

from arka.media.slide_design import (
    contrast_ratio,
    is_traction_slide,
    palette_meets_wcag_aa,
    slide_palette,
    slide_typography,
    spacing_units,
    title_font_family,
)


def test_spacing_units_eight_px_grid():
    assert spacing_units(1) == 8 / 1080
    assert spacing_units(3) == 24 / 1080


def test_contrast_ratio_dark_on_light():
    ratio = contrast_ratio("#0f172a", "#f8fafc")
    assert ratio > 10


def test_pitch_dark_palette_wcag_aa():
    palette = slide_palette("pitch", "dark")
    assert palette_meets_wcag_aa(palette)


def test_executive_light_palette_wcag_aa():
    palette = slide_palette("executive", "light")
    assert palette_meets_wcag_aa(palette)


def test_typography_font_pairing():
    pitch = slide_typography("pitch")
    academic = slide_typography("academic")
    assert pitch.title_font == "sans-serif"
    assert pitch.body_font == "sans-serif"
    assert academic.title_font == "serif"
    assert title_font_family("academic") == "serif"


def test_is_traction_slide_pitch_only():
    assert is_traction_slide("Early traction proves the model", style="pitch")
    assert not is_traction_slide("Early traction proves the model", style="executive")
    assert is_traction_slide("Growth metrics this quarter", style="pitch")
