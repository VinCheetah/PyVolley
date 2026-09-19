"""Tests pour l'assainissement et la validation des noms d'équipe et de club."""

import pytest
from pyvolley.core.models import Equipe, Club
from pyvolley.parsers.utils import clean_team_name
from pyvolley.parsers.extractors.fast.rosters import extract_fast_rosters
from pyvolley.parsers.layout_config import ParserLayoutConfig


def test_equipe_nom_validation_too_short_or_punctuation():
    """Vérifie que des entrées trop courtes ou uniquement de la ponctuation lèvent ValidationError."""
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        Equipe(nom=",")

    with pytest.raises(ValidationError):
        Equipe(nom=" - ")

    with pytest.raises(ValidationError):
        Equipe(nom="")

    with pytest.raises(ValidationError):
        Equipe(nom="A")


def test_equipe_nom_validation_trailing_punctuation():
    """Vérifie que les virgules ou ponctuations parasites en début/fin de nom sont élaguées."""
    eq = Equipe(nom="PARIS VOLLEY,")
    assert eq.nom == "PARIS VOLLEY"

    eq2 = Equipe(nom=", AS CANNES VB - ")
    assert eq2.nom == "AS CANNES VB"


def test_club_nom_validation():
    """Vérifie que Club.nom élague les ponctuations et valide la longueur."""
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        Club(nom=",")

    club2 = Club(nom="RENNES EC,")
    assert club2.nom == "RENNES EC"


def test_clean_team_name_punctuation():
    """Vérifie le comportement de clean_team_name sur des entrées parasites."""
    assert clean_team_name(",") == ""
    assert clean_team_name(" , ") == ""
    assert clean_team_name("-") == ""
    assert clean_team_name("US VILLEJUIF, ") == "US VILLEJUIF"
    assert clean_team_name("MONTPELLIER VB B") == "MONTPELLIER VB"


def test_extract_fast_rosters_with_comma_team_name():
    """Vérifie que extract_fast_rosters ne plante pas lorsque nom_gauche ou nom_droite vaut ','."""
    config = ParserLayoutConfig()
    eq_a, eq_b, _, _ = extract_fast_rosters(
        sorted_words=[],
        y0_list=[],
        config=config,
        nom_gauche=",",
        nom_droite="PARIS VOLLEY",
        gauche_est_equipe_a=True,
    )
    assert eq_a.nom == "Équipe A"
    assert eq_b.nom == "PARIS VOLLEY"
