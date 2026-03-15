"""Tests unitaires pour le branding club (couleurs + logo)."""

from types import SimpleNamespace

from pyvolley.web.helpers.club_branding import parse_club_colors, detect_club_logo_url


def test_parse_club_colors_handles_basic_french_names() -> None:
    branding = parse_club_colors("Bleu et Blanc")

    assert branding["primary"] == "#2563EB"
    assert branding["secondary"] == "#F9FAFB"
    assert branding["tokens"] == ["Bleu", "Blanc"]


def test_detect_club_logo_prefers_logo_like_images(monkeypatch) -> None:
    html = """
    <html>
      <body>
        <img src="/images/banner.png" alt="Bannière">
        <img src="/uploads/clubs/logo_0622126.png" alt="Logo club">
        <img src="/images/facebook.png" alt="Facebook">
      </body>
    </html>
    """

    def fake_get(url, headers=None, timeout=None):
        return SimpleNamespace(
            status_code=200,
            headers={"content-type": "text/html; charset=utf-8"},
            text=html,
        )

    monkeypatch.setattr("pyvolley.web.helpers.club_branding.requests.get", fake_get)
    detect_club_logo_url.cache_clear()

    logo = detect_club_logo_url(
        "https://exemple.ffvb.test/planning_club.php?cnclub=0622126",
        None,
        "0622126",
    )

    assert logo == "https://exemple.ffvb.test/uploads/clubs/logo_0622126.png"
