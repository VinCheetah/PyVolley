from pyvolley.web.helpers.niveau import (
    niveau_reference_labels,
    niveau_sort_rank,
    resolve_niveau_badge,
)


def test_youth_cdf_badge_is_specific_and_lower_rank():
    badge = resolve_niveau_badge(
        niveau=None,
        competition_name="Coupe de France M15",
        categorie="M15",
        division=None,
    )

    assert badge == {"label": "Jeunes CdF", "css_class": "badge-cyan"}
    assert niveau_sort_rank("Jeunes CdF") < niveau_sort_rank("Regional")
    assert niveau_sort_rank("Jeunes CdF") < niveau_sort_rank("N3")


def test_senior_cdf_keeps_top_label():
    badge = resolve_niveau_badge(
        niveau=None,
        competition_name="Coupe de France Pro Masculine",
        categorie=None,
        division=None,
    )

    assert badge == {"label": "CdF", "css_class": "badge-purple"}


def test_reference_level_order_is_explicit_and_sorted():
    refs = niveau_reference_labels()

    assert refs[0]["label"] == "Loisir"
    assert refs[-1]["label"] == "CdF"

    ranks = [item["rank"] for item in refs]
    assert ranks == sorted(ranks)
    assert len(ranks) == len(set(ranks))
