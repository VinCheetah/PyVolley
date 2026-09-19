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


def test_accession_regionale_and_nationale_classification():
    badge_ar = resolve_niveau_badge(
        niveau=None,
        competition_name="ACCESSION REGIONALE MASCULINE",
    )
    assert badge_ar == {"label": "Préreg", "css_class": "badge-teal"}

    badge_an = resolve_niveau_badge(
        niveau=None,
        competition_name="ACCESSION A LA NATIONALE 3",
    )
    assert badge_an == {"label": "Prénat", "css_class": "badge-orange"}


def test_4x4_is_not_classified_as_division_4():
    badge_4x4 = resolve_niveau_badge(
        niveau="DEPARTEMENTAL",
        competition_name="CHAMPIONNAT SENIOR 4X4 DEPARTEMENTAL",
    )
    assert badge_4x4["label"] == "Dép"
    assert badge_4x4["label"] != "D4"


def test_youth_poule_code_is_not_classified_as_division():
    badge_youth = resolve_niveau_badge(
        niveau=None,
        competition_name="3MG POULE TITRE",
        categorie="M13",
    )
    # Ne doit pas être pris pour une D3
    assert badge_youth["label"] != "D3"
    assert badge_youth["label"] != "Jeunes D3"


def test_n1_has_elite_rank():
    badge_n1 = resolve_niveau_badge(
        niveau=None,
        competition_name="NATIONALE 1 MASCULINE",
    )
    badge_elite = resolve_niveau_badge(
        niveau=None,
        competition_name="ELITE MASCULINE",
    )
    assert badge_n1["label"] == "N1"
    assert badge_elite["label"] == "Elite"
    assert niveau_sort_rank(badge_n1["label"]) == niveau_sort_rank(badge_elite["label"]) == 15

