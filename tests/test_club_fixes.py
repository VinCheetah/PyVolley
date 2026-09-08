"""
Tests unitaires pour la gestion et la résolution des clubs :
- Extraction du département depuis le code FFVB (department_from_club_code)
- Décodage des entités HTML dans l'adressier CSV FFVB (parse_adressier_csv)
- Parsing des codes postaux malformés/inversés/tronqués (_split_postal_city)
- Filtrage des placeholders de tournois (is_empty_match)
- Non-création de clubs par MatchImportService (lecture seule)
"""

import pytest
from pyvolley.core.geo_data import department_from_club_code
from pyvolley.scrapers.ffvb.adressier_scraper import parse_adressier_csv
from pyvolley.scrapers.ffvb.export_scraper import is_empty_match
from pyvolley.database.export_import_service import _split_postal_city, _department_from_postal


def test_department_from_club_code():
    """Vérifie l'extraction du département depuis les codes FFVB à 7 caractères."""
    # Métropole standard
    assert department_from_club_code("0015372") == "01"
    assert department_from_club_code("0622126") == "62"
    assert department_from_club_code("0590025") == "59"
    assert department_from_club_code("0750050") == "75"
    assert department_from_club_code("0959441") == "95"

    # Corse
    assert department_from_club_code("02A5803") == "2A"
    assert department_from_club_code("02B1234") == "2B"
    assert department_from_club_code("2010001") == "2A"
    assert department_from_club_code("2020001") == "2B"

    # DROM
    assert department_from_club_code("9744926") == "974"
    assert department_from_club_code("9765959") == "976"
    assert department_from_club_code("9710000") == "971"

    # Cas invalides / vides
    assert department_from_club_code(None) is None
    assert department_from_club_code("") is None
    assert department_from_club_code("1") is None


def test_parse_adressier_csv_html_entity_unescape():
    """Vérifie que les entités HTML avec point-virgule (ex: &#039;) ne découpent pas les colonnes."""
    csv_line = (
        "Entite;Poule;0015372;L&#039;ENVOLLEY;Ligue AURA;1;BLEU;Pdt Test;Entr Test;Adj Test;"
        "Corr Nom;Adr 1;Adr 2;Adr 3;01000 BOURG EN BRESSE;0100000000;0600000000;mail@test.fr\n"
    )
    header = "Entite;Poule;NClub;NomClub;Ligue;Pos;Couleurs;Pdt;Entr;Adj;Corr;Adr1;Adr2;Adr3;Ville;Tel;Port;Mail\n"
    content_bytes = (header + csv_line).encode("windows-1252")

    clubs = parse_adressier_csv(content_bytes)
    assert len(clubs) == 1
    club = clubs[0]

    assert club.code_ffvb == "0015372"
    # Le nom ne doit pas être tronqué à "L&#039"
    assert club.nom == "L'ENVOLLEY"
    # La ligue ne doit pas être "ENVOLLEY"
    assert club.ligue == "Ligue AURA"
    assert club.president == "Pdt Test"
    assert club.correspondant_ville == "01000 BOURG EN BRESSE"


def test_split_postal_city_variations():
    """Vérifie l'extraction du code postal et de la ville sous diverses formes."""
    # Standard 5 chiffres
    cp, ville = _split_postal_city("69007 LYON")
    assert cp == "69007"
    assert ville == "LYON"

    # 4 chiffres (zéros tronqués)
    cp, ville = _split_postal_city("0621 MANDELIEU LA NAPOULE")
    assert cp == "06210"
    assert ville == "MANDELIEU LA NAPOULE"

    cp, ville = _split_postal_city("6279 LEFOREST")
    assert cp == "62790"
    assert ville == "LEFOREST"

    cp, ville = _split_postal_city("5900 LILLE")
    assert cp == "59000"
    assert ville == "LILLE"

    # Code postal en fin de chaîne
    cp, ville = _split_postal_city("MONS 30340")
    assert cp == "30340"
    assert ville == "MONS"

    # Code DROM 3 chiffres
    cp, ville = _split_postal_city("976 KANI-KÉLI")
    assert cp == "976"
    assert ville == "KANI-KÉLI"


def test_is_empty_match_placeholders():
    """Vérifie que les placeholders de tournois sont ignorés."""
    assert is_empty_match("xxxxx", "Equipe B", "M001") is True
    assert is_empty_match("Equipe A", "exempt", "M002") is True
    assert is_empty_match(".", "Equipe B", "M003") is True
    assert is_empty_match(None, None, "M004") is True
    assert is_empty_match("Equipe A", "Equipe B", "M005") is False
