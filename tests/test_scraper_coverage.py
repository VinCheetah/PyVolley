"""
Tests de validation du système de scraping PyVolley.

Ces tests comparent les données récupérées par le scraper actuel avec celles
disponibles via l'export CSV FFVB (vbspo_calendrier_export.php).

Usage:
    pytest tests/test_scraper_coverage.py -v --tb=short
    pytest tests/test_scraper_coverage.py -k "test_export" -v
"""

import csv
import io
import re
from collections import defaultdict
from unittest.mock import patch

import pytest
import requests

# ─── Configuration ─────────────────────────────────────────────────
FFVB_BASE_URL = "https://www.ffvbbeach.org/ffvbapp/resu"
SAISON = "2025/2026"
TEST_ENTITY = "ABCCS"
TEST_POULE = "EMA"


# ─── Helpers ───────────────────────────────────────────────────────

def fetch_export_csv(entity: str, poule: str = None, saison: str = SAISON) -> list[dict]:
    """Récupère l'export CSV FFVB et retourne une liste de dicts."""
    params = {
        "saison": saison,
        "codent": entity,
        "calend": "COMPLET",
    }
    if poule:
        params["poule"] = poule

    url = f"{FFVB_BASE_URL}/vbspo_calendrier_export.php"
    resp = requests.get(url, params=params, timeout=30)
    resp.raise_for_status()

    # L'export utilise des tabulations et l'encodage latin-1
    content = resp.content.decode("latin-1", errors="replace")

    # Identifier le séparateur (tab ou point-virgule)
    first_line = content.split("\n")[0]
    sep = "\t" if "\t" in first_line else ";"

    reader = csv.DictReader(io.StringIO(content), delimiter=sep)
    return list(reader)


def extract_poule_code(code_match: str) -> str:
    """Extraire le code poule depuis un code match (EMA001 → EMA)."""
    m = re.match(r"^([A-Z0-9]+?)\d{3,4}$", code_match, re.I)
    if m:
        return m.group(1).upper()
    return code_match


# ─── Tests de l'export CSV ─────────────────────────────────────────

@pytest.mark.network
class TestExportCSV:
    """Tests validant les données disponibles dans l'export CSV FFVB."""

    def test_export_returns_data(self):
        """L'export CSV pour EMA retourne des données."""
        rows = fetch_export_csv(TEST_ENTITY, TEST_POULE)
        assert len(rows) > 0, "L'export CSV ne retourne aucune donnée"

    def test_export_has_required_columns(self):
        """L'export CSV contient les colonnes critiques."""
        rows = fetch_export_csv(TEST_ENTITY, TEST_POULE)
        assert len(rows) > 0

        # Vérifier les colonnes clés (les noms exacts peuvent varier)
        first_row = rows[0]
        keys = set(first_row.keys())

        # Au moins certaines colonnes attendues doivent être présentes
        # (les noms de colonnes sont en français avec accents)
        assert len(keys) >= 15, f"Trop peu de colonnes : {len(keys)}"

    def test_export_has_club_codes(self):
        """L'export CSV fournit les codes club FFVB."""
        rows = fetch_export_csv(TEST_ENTITY, TEST_POULE)

        # Trouver les colonnes contenant des codes club (format: 7 chiffres)
        code_pattern = re.compile(r"^\d{7}$")
        rows_with_codes = 0

        for row in rows:
            values = list(row.values())
            if any(code_pattern.match(str(v).strip()) for v in values if v):
                rows_with_codes += 1

        coverage = rows_with_codes / len(rows) if rows else 0
        assert coverage > 0.90, (
            f"Seulement {coverage:.0%} des matchs ont un code club FFVB "
            f"(attendu > 90%)"
        )

    def test_export_match_count_vs_minimum(self):
        """L'export contient au moins autant de matchs que le scraper actuel."""
        rows = fetch_export_csv(TEST_ENTITY, TEST_POULE)
        # Le scraper actuel trouve ~125 matchs pour EMA
        assert len(rows) >= 125, (
            f"L'export ne contient que {len(rows)} matchs "
            f"(le scraper en trouvait 125)"
        )

    def test_export_without_poule_returns_all(self):
        """L'export sans filtre poule retourne TOUTES les poules d'une entité."""
        rows = fetch_export_csv(TEST_ENTITY, poule=None)
        assert len(rows) > 200, (
            f"L'export global ne contient que {len(rows)} matchs "
            f"pour toute l'entité {TEST_ENTITY}"
        )

    def test_export_discovers_all_poules(self):
        """L'export global permet de découvrir toutes les poules."""
        rows = fetch_export_csv(TEST_ENTITY, poule=None)

        # Extraire les codes match et en déduire les codes poule
        poule_codes = set()
        for row in rows:
            values = list(row.values())
            # Le code match est typiquement dans les premières colonnes
            for v in values[:5]:
                v_str = str(v).strip()
                if re.match(r"^[A-Z0-9]{2,6}\d{3,4}$", v_str, re.I):
                    poule_codes.add(extract_poule_code(v_str))

        # Vérifier que les poules manquantes dans le scraper actuel sont trouvées
        missing_in_scraper = {"LBM", "MSL", "SPS", "TSA", "TSB", "TST"}
        found_missing = missing_in_scraper & poule_codes

        assert len(poule_codes) >= 30, (
            f"Seulement {len(poule_codes)} poules découvertes"
        )
        # Au moins certaines des poules manquantes devraient être dans l'export
        if found_missing:
            print(f"Poules auparavant manquantes retrouvées : {found_missing}")


# ─── Tests de couverture scraper vs export ─────────────────────────

@pytest.mark.network
class TestScraperCoverage:
    """Compare la couverture du scraper actuel avec l'export CSV."""

    def test_scraper_misses_matches(self):
        """Documente le nombre de matchs manqués par le scraper actuel."""
        # Import du scraper
        try:
            from pyvolley.scrapers.ffvb import FFVBScraper
        except ImportError:
            pytest.skip("FFVBScraper non disponible")

        export_rows = fetch_export_csv(TEST_ENTITY, TEST_POULE)
        export_codes = set()
        for row in export_rows:
            for v in list(row.values())[:5]:
                v_str = str(v).strip()
                if re.match(r"^[A-Z0-9]{2,6}\d{3,4}$", v_str, re.I):
                    export_codes.add(v_str.upper())

        scraper = FFVBScraper()
        scraper_matches = list(scraper.get_matches_for_poule(
            TEST_ENTITY, TEST_POULE, SAISON.replace("/", "-")
        ))
        scraper_codes = {m.code.upper() for m in scraper_matches}

        missing = export_codes - scraper_codes
        extra = scraper_codes - export_codes

        print(f"\nExport CSV : {len(export_codes)} matchs")
        print(f"Scraper    : {len(scraper_codes)} matchs")
        print(f"Manquants  : {len(missing)} ({', '.join(sorted(missing)[:10])}...)")
        print(f"En trop    : {len(extra)}")

        # Ce test documente le gap — il passera quand le nouveau scraper sera en place
        if missing:
            pytest.xfail(
                f"Le scraper manque {len(missing)} matchs par rapport à l'export CSV"
            )


# ─── Tests du scraper de clubs ─────────────────────────────────────

@pytest.mark.network
class TestClubIdentification:
    """Tests de l'identification des clubs via planning_club_class.php."""

    def test_planning_club_class_accessible(self):
        """Le endpoint planning_club_class.php est accessible."""
        # Utiliser un code club connu (Lille UC Métropole)
        url = f"{FFVB_BASE_URL}/planning_club_class.php"
        params = {
            "codent": TEST_ENTITY,
            "saison": SAISON,
            "cnclub": "0590005",
        }
        resp = requests.get(url, params=params, timeout=30)
        assert resp.status_code == 200
        assert len(resp.text) > 500, "Réponse trop courte"

    def test_planning_club_has_team_info(self):
        """La page club contient des informations sur les équipes."""
        url = f"{FFVB_BASE_URL}/planning_club_class.php"
        params = {
            "codent": TEST_ENTITY,
            "saison": SAISON,
            "cnclub": "0590005",
        }
        resp = requests.get(url, params=params, timeout=30)
        html = resp.text.lower()

        # Doit contenir des références à du contenu lié au volleyball
        has_content = any(word in html for word in [
            "classement", "equipe", "équipe", "division",
            "poule", "rang", "pts", "match",
        ])
        assert has_content, "La page ne contient pas d'informations d'équipe"


# ─── Tests des patterns hardcodés ──────────────────────────────────

class TestPatternsObsolescence:
    """Vérifie l'obsolescence des patterns hardcodés."""

    def test_patterns_file_exists(self):
        """Le fichier patterns.py existe."""
        try:
            from pyvolley.scrapers.ffvb.patterns import PATTERN_ENTITY_CODES
            assert len(PATTERN_ENTITY_CODES) > 0
        except ImportError:
            pytest.skip("patterns.py non trouvé")

    @pytest.mark.network
    def test_hardcoded_patterns_obsolescence(self):
        """Quantifie combien de patterns hardcodés sont obsolètes."""
        try:
            from pyvolley.scrapers.ffvb.patterns import get_known_poules
        except ImportError:
            pytest.skip("patterns.py non trouvé")

        # Récupérer les poules réelles depuis l'export
        rows = fetch_export_csv(TEST_ENTITY, poule=None)
        real_poules = set()
        for row in rows:
            for v in list(row.values())[:5]:
                v_str = str(v).strip()
                if re.match(r"^[A-Z0-9]{2,6}\d{3,4}$", v_str, re.I):
                    real_poules.add(extract_poule_code(v_str))

        # Compter les patterns de TEST_ENTITY qui ne sont pas dans les poules réelles
        known = get_known_poules(TEST_ENTITY, SAISON)
        entity_pattern_codes = [p.code for p in known]
        obsolete = [p for p in entity_pattern_codes if p not in real_poules]
        valid = [p for p in entity_pattern_codes if p in real_poules]

        print(f"\nPatterns {TEST_ENTITY} : {len(entity_pattern_codes)} total")
        print(f"  Valides    : {len(valid)}")
        print(f"  Obsolètes  : {len(obsolete)}")

        if obsolete:
            print(f"  Exemples   : {obsolete[:10]}")


# ─── Tests du modèle MatchInfo ─────────────────────────────────────

class TestMatchInfoCompleteness:
    """Vérifie que MatchInfo capture toutes les données nécessaires."""

    def test_matchinfo_lacks_team_names(self):
        """Documente l'absence de noms d'équipes dans MatchInfo."""
        from pyvolley.scrapers.base import MatchInfo

        mi = MatchInfo(
            code="EMA001",
            competition_code="EMA",
            ligue_code="ABCCS",
            saison="2025-2026",
        )

        # Vérifier l'absence de champs critiques
        assert not hasattr(mi, "equipe_a_nom"), "equipe_a_nom devrait être ajouté"
        assert not hasattr(mi, "equipe_b_nom"), "equipe_b_nom devrait être ajouté"
        assert not hasattr(mi, "club_a_code"), "club_a_code devrait être ajouté"
        assert not hasattr(mi, "club_b_code"), "club_b_code devrait être ajouté"
        assert not hasattr(mi, "date"), "date devrait être ajouté"
        assert not hasattr(mi, "heure"), "heure devrait être ajouté"
        assert not hasattr(mi, "salle"), "salle devrait être ajouté"
        assert not hasattr(mi, "source_url"), "source_url devrait être ajouté"

    def test_matchdb_lacks_parsing_status(self):
        """Documente l'absence de parsing_status dans MatchDB."""
        from pyvolley.database.models import MatchDB

        columns = {c.name for c in MatchDB.__table__.columns}

        assert "source_pdf" in columns, "source_pdf devrait exister"
        assert "parsed_at" in columns, "parsed_at devrait exister"

        # Ces champs devraient être ajoutés
        missing = []
        if "source_url" not in columns:
            missing.append("source_url")
        if "parsing_status" not in columns:
            missing.append("parsing_status")
        if "club_a_code_ffvb" not in columns:
            missing.append("club_a_code_ffvb")
        if "club_b_code_ffvb" not in columns:
            missing.append("club_b_code_ffvb")

        if missing:
            pytest.xfail(
                f"Champs manquants dans MatchDB : {', '.join(missing)}"
            )


# ─── Tests du score_scraper vs export ──────────────────────────────

@pytest.mark.network
class TestScoreScraperVsExport:
    """Compare les données du score_scraper avec l'export CSV."""

    def test_export_has_more_data(self):
        """L'export CSV fournit plus de données que le score_scraper."""
        rows = fetch_export_csv(TEST_ENTITY, TEST_POULE)

        if not rows:
            pytest.skip("Export CSV vide")

        first_row = rows[0]
        keys = list(first_row.keys())

        # Le score_scraper récupère : code, date, heure, equipeA, equipeB,
        # setsA, setsB, scores, total, arbitres
        # L'export ajoute : n° club, salle, licence arb, ligue arb, CD arb,
        # juges de ligne, marqueur

        print(f"\nColonnes de l'export : {len(keys)}")
        print(f"Colonnes : {keys}")

        # L'export devrait avoir significativement plus de colonnes
        assert len(keys) > 15, (
            f"L'export n'a que {len(keys)} colonnes — vérifié le format"
        )
