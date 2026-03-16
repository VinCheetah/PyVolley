"""Tests unitaires pour le branding club (couleurs + logo explicite)."""

from pyvolley.web.helpers.club_branding import parse_club_colors, build_club_branding


def test_parse_club_colors_handles_basic_french_names() -> None:
    branding = parse_club_colors("Bleu et Blanc")

    assert branding["primary"] == "#2563EB"
    assert branding["secondary"] == "#F9FAFB"
    assert branding["tokens"] == ["Bleu", "Blanc"]


def test_build_club_branding_uses_explicit_logo_url() -> None:
    branding = build_club_branding(
        "Rouge et Noir",
        "https://volleybox.net/media/upload/teams/club_logo.png",
    )

    assert branding["logo_url"] == "https://volleybox.net/media/upload/teams/club_logo.png"
    assert branding["primary"] == "#DC2626"
