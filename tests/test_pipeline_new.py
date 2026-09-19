"""
Tests complets pour le nouveau pipeline PyVolley (validation, scrapers, parsers, services, orchestrateur).
"""

from __future__ import annotations

from datetime import date
import pytest

from pyvolley.database.models import (
    EntiteFFVBDB,
    ClubDB,
    CompetitionDB,
    PouleDB,
    MatchDB,
    SaisonDB,
)
from pyvolley.pipeline.validation import (
    validate_entity_code,
    validate_club_code,
    validate_poule_code,
    validate_match_code,
    validate_saison,
    validate_date,
    validate_time,
    validate_score_sets,
    validate_set_points,
    ValidationError,
)
from pyvolley.pipeline.context import PipelineContext
from pyvolley.pipeline.parsers.entity_parser import parse_entities_from_html
from pyvolley.pipeline.parsers.club_parser import parse_clubs_from_annuaire_html
from pyvolley.pipeline.parsers.template_parser import extract_age_and_gender_from_sheet_000
from pyvolley.pipeline.parsers.level_parser import (
    classify_poule,
    extract_play_format,
    extract_variant,
)
from pyvolley.pipeline.parsers.competition_parser import parse_competition_home_html
from pyvolley.pipeline.parsers.match_parser import parse_export_csv_content
from pyvolley.pipeline.services.entity_service import EntityService
from pyvolley.pipeline.services.club_service import ClubService
from pyvolley.pipeline.services.competition_service import CompetitionService
from pyvolley.pipeline.services.match_service import MatchService
from pyvolley.pipeline.orchestrator import PipelineOrchestrator


# ═════════════════════════════════════════════════════════════════════════════
# 1. Tests Validation
# ═════════════════════════════════════════════════════════════════════════════

def test_validation_entity_code():
    assert validate_entity_code("ABCCS") == "ABCCS"
    assert validate_entity_code(" ptpl53 ") == "PTPL53"
    assert validate_entity_code("LIIDF") == "LIIDF"
    with pytest.raises(ValidationError):
        validate_entity_code("INVALID_ENTITY_CODE_TOO_LONG")
    with pytest.raises(ValidationError):
        validate_entity_code("A")  # Moins de 2 caractères
    with pytest.raises(ValidationError):
        validate_entity_code("AB@CD")  # Caractères invalides


def test_validation_club_code():
    assert validate_club_code("0750001") == "0750001"
    assert validate_club_code("750001") == "0750001"
    assert validate_club_code(750001) == "0750001"
    assert validate_club_code(530012) == "0530012"
    with pytest.raises(ValidationError):
        validate_club_code("ABCDEFG")
    with pytest.raises(ValidationError):
        validate_club_code("12345678")  # 8 chiffres


def test_validation_poule_code():
    assert validate_poule_code("EMA") == "EMA"
    assert validate_poule_code("1ma") == "1MA"
    # Poules de plus de 3 caractères (suffixes Aller/Retour) sont normalisées aux 3 premiers
    assert validate_poule_code("EMAA") == "EMA"
    with pytest.raises(ValidationError):
        validate_poule_code("E1")  # Moins de 3 caractères


def test_validation_match_code():
    poule, num = validate_match_code("EMA001")
    assert poule == "EMA"
    assert num == "001"

    poule2, num2 = validate_match_code("1MB105")
    assert poule2 == "1MB"
    assert num2 == "105"

    with pytest.raises(ValidationError):
        validate_match_code("EMA")


def test_validation_date_and_time():
    assert validate_date("2024-10-15") == date(2024, 10, 15)
    assert validate_date("15/10/2024") == date(2024, 10, 15)
    assert validate_date(None) is None
    with pytest.raises(ValidationError):
        validate_date("99/99/9999")

    assert validate_time("20:30") == "20:30"
    assert validate_time("20h30") == "20:30"
    assert validate_time(None) is None


def test_validation_score_sets():
    assert validate_score_sets("3/1") == "3/1"
    assert validate_score_sets("3-0") == "3/0"
    assert validate_score_sets("3/P") == "3/P"
    assert validate_score_sets("P/3") == "P/3"
    with pytest.raises(ValidationError):
        validate_score_sets("invalid_score")


def test_validation_set_points():
    assert validate_set_points("25-20") == (25, 20)
    assert validate_set_points("26/24") == (26, 24)
    with pytest.raises(ValidationError):
        validate_set_points("25")
    with pytest.raises(ValidationError):
        validate_set_points("invalid")


# ═════════════════════════════════════════════════════════════════════════════
# 2. Tests Entity Parsing & Service
# ═════════════════════════════════════════════════════════════════════════════

def test_entity_parser():
    sample_html = """
    <html>
        <body>
            <select name="sel_entites">
                <option value="0">Choisir...</option>
                <option value="LIIDF">Ligue d'Ile de France</option>
                <option value="PTPL53">Comité de la Mayenne (53)</option>
                <option value="AVBEACH">Beach Volley France</option>
            </select>
        </body>
    </html>
    """
    entities = parse_entities_from_html(sample_html)
    assert len(entities) >= 3

    by_code = {e.code: e for e in entities}
    assert "LIIDF" in by_code
    assert by_code["LIIDF"].echelon == "Regional"
    assert by_code["LIIDF"].type == "ligue"
    assert by_code["LIIDF"].variante == "Standard"

    assert "PTPL53" in by_code
    assert by_code["PTPL53"].echelon == "Departemental"
    assert by_code["PTPL53"].type == "comite"
    assert by_code["PTPL53"].numero_departement == "53"

    assert "AVBEACH" in by_code
    assert by_code["AVBEACH"].echelon == "National"
    assert by_code["AVBEACH"].variante == "Beach"


def test_entity_service(test_session):
    ctx = PipelineContext(session=test_session, saison="2024/2025")
    service = EntityService(ctx)

    sample_html = """
    <html>
        <body>
            <select name="sel_entites">
                <option value="LIIDF">Ligue d'Ile de France</option>
                <option value="PTPL53">Comité de la Mayenne (53)</option>
            </select>
        </body>
    </html>
    """
    service.sync_entities(html=sample_html)

    assert "LIIDF" in ctx.entity_cache
    assert "PTPL53" in ctx.entity_cache

    ent_53 = service.get_entity("PTPL53")
    assert ent_53 is not None
    assert ent_53.code == "PTPL53"


# ═════════════════════════════════════════════════════════════════════════════
# 3. Tests Club Parsing & Service
# ═════════════════════════════════════════════════════════════════════════════

def test_club_parser():
    sample_html = """
    <table>
        <tr>
            <td>0750001</td>
            <td>PARIS VOLLEY CLUB</td>
            <td>Ligue IDF</td>
            <td>CD 75</td>
        </tr>
        <tr>
            <td>530012</td>
            <td>LAVAL VOLLEY 53</td>
            <td>Ligue PDL</td>
            <td>CD 53</td>
        </tr>
    </table>
    """
    clubs = parse_clubs_from_annuaire_html(sample_html)
    assert len(clubs) == 2
    assert clubs[0].code_ffvb == "0750001"
    assert clubs[1].code_ffvb == "0530012"  # Padded to 7 digits


def test_club_service(test_session):
    ctx = PipelineContext(session=test_session, saison="2024/2025")
    service = ClubService(ctx)

    sample_html = """
    <table>
        <tr>
            <td>0750001</td>
            <td>PARIS VOLLEY</td>
            <td>Ligue IDF</td>
            <td>CD 75</td>
        </tr>
    </table>
    """
    service.sync_clubs_from_annuaire(html_text=sample_html)

    assert "0750001" in ctx.club_cache
    club = service.get_club("0750001")
    assert club is not None
    assert club.nom == "PARIS VOLLEY"


# ═════════════════════════════════════════════════════════════════════════════
# 4. Tests Level & Specificity Parsing
# ═════════════════════════════════════════════════════════════════════════════

def test_format_and_variant_extraction():
    format_jeu = extract_play_format("Championnat 4x4 Excellence D1")
    assert format_jeu == "4x4"

    format_jeu = extract_play_format("Régionale 6x6 Masculine")
    assert format_jeu == "6x6"

    variante = extract_variant("Tournoi Beach Volley Senior")
    assert variante == "Beach"

    variante = extract_variant("Coupe Volley Assis Mixte")
    assert variante == "Assis"


def test_classify_poule():
    # National entity with Elite Poule
    p1 = classify_poule(
        entity_code="ABCCS",
        entity_type="nationale",
        age="Senior",
        gender="Masculin",
        competition_name="Championnat de France Elite Masculin",
        poule_name="Poule A",
        poule_code="EMA",
    )
    assert p1.echelon == "National"
    assert p1.niveau == "Elite"
    assert p1.genre == "Masculin"
    assert p1.categorie == "Senior"

    # Committee entity CANNOT be National, even if name says "Nationale 3"
    p2 = classify_poule(
        entity_code="CD75",
        entity_type="comite",
        age="Senior",
        gender="Masculin",
        competition_name="Accession Nationale 3",
        poule_name="Poule 1",
        poule_code="D1M",
    )
    assert p2.echelon == "Departemental"
    assert p2.niveau == "D1"

    # Regional entity with Prenat
    p3 = classify_poule(
        entity_code="LIIDF",
        entity_type="ligue",
        age="Senior",
        gender="Feminin",
        competition_name="Prénationale Féminine",
        poule_name="Poule Unique",
        poule_code="PNF",
    )
    assert p3.echelon == "Regional"
    assert p3.niveau == "Prenat"
    assert p3.genre == "Feminin"

    # Youth M18
    p4 = classify_poule(
        entity_code="CD53",
        entity_type="comite",
        age="M18",
        gender="Feminin",
        competition_name="Championnat M18 Féminin 4x4",
        poule_name="Poule A",
        poule_code="M18",
    )
    assert p4.echelon == "Departemental"
    assert p4.categorie == "M18"
    assert p4.genre == "Feminin"
    assert p4.format_jeu == "4x4"


# ═════════════════════════════════════════════════════════════════════════════
# 5. Tests Competition & Poule Service
# ═════════════════════════════════════════════════════════════════════════════

def test_competition_service(test_session):
    ctx = PipelineContext(session=test_session, saison="2024/2025")
    entite = EntiteFFVBDB(
        code="LIIDF",
        nom="Ligue IDF",
        type="ligue",
    )
    test_session.add(entite)
    test_session.commit()
    ctx.entity_cache["LIIDF"] = entite

    sample_html = """
    <html>
        <body>
            <div class="compet_title">Régionale 1 Masculine</div>
            <a href="vbspo_calendrier.php?poule=R1M">Poule A</a>
        </body>
    </html>
    """

    service = CompetitionService(ctx)
    poules_map = service.sync_entity_competitions(
        entite_code="LIIDF",
        inspect_template_000=False,
        html_text=sample_html,
    )

    assert "R1M" in poules_map
    poule_db = poules_map["R1M"]
    assert poule_db.code == "R1M"
    assert poule_db.echelon == "Regional"
    assert poule_db.niveau == "R1"
    assert poule_db.genre == "Masculin"


# ═════════════════════════════════════════════════════════════════════════════
# 6. Tests Match Parser & Match Service
# ═════════════════════════════════════════════════════════════════════════════

def test_match_parser():
    # En-tête et ligne exactes selon l'export FFVB standard
    csv_content = (
        "Entite;Journee;Match;Date;Heure;EQA_no;EQA_nom;EQB_no;EQB_nom;Set;Score;Total;Salle;Arb1_Lic;Arb1_Nom\n"
        "LIIDF;1;R1M001;15/10/2024;20h30;0750001;PARIS VOLLEY;0530012;LAVAL 53;3/1;25-20,20-25,25-22,25-18;95-85;Gymnase Coubertin;12345;DUPONT Jean\n"
    ).encode("latin-1")

    matches = parse_export_csv_content(csv_content, default_entite_code="LIIDF")
    assert len(matches) == 1
    m = matches[0]
    assert m.code_match == "R1M001"
    assert m.poule_code_3 == "R1M"
    assert m.date_match == date(2024, 10, 15)
    assert m.heure_match == "20:30"
    assert m.score_sets == "3/1"
    assert len(m.sets_points) == 4
    assert m.sets_points[0] == (25, 20)
    assert m.club_a_code_7 == "0750001"
    assert m.club_b_code_7 == "0530012"


def test_match_service(test_session):
    ctx = PipelineContext(session=test_session, saison="2024/2025")

    # Pre-create Entite, Poule, and Clubs
    entite = EntiteFFVBDB(code="LIIDF", nom="Ligue IDF", type="ligue")
    test_session.add(entite)
    test_session.flush()

    comp = CompetitionDB(
        nom="Régionale 1",
        code_competition="COMP1",
        entite_id=entite.id,
        saison_id=ctx.saison_db.id,
    )
    test_session.add(comp)
    test_session.flush()

    poule = PouleDB(
        code="R1M",
        nom="Poule A",
        competition_id=comp.id,
        echelon="Regional",
        niveau="R1",
        genre="Masculin",
    )
    test_session.add(poule)

    club_a = ClubDB(code_ffvb="0750001", nom="PARIS VOLLEY")
    club_b = ClubDB(code_ffvb="0530012", nom="LAVAL 53")
    test_session.add_all([club_a, club_b])
    test_session.commit()

    # Warm caches
    ctx.entity_cache["LIIDF"] = entite
    ctx.poule_cache[("R1M", "LIIDF")] = poule
    ctx.club_cache["0750001"] = club_a
    ctx.club_cache["0530012"] = club_b

    csv_content = (
        "Entite;Journee;Match;Date;Heure;EQA_no;EQA_nom;EQB_no;EQB_nom;Set;Score;Total;Salle;Arb1_Lic;Arb1_Nom;Arb1_LR;Arb1_CD;Arb2_Lic;Arb2_Nom\n"
        "LIIDF;1;R1M001;15/10/2024;20h30;0750001;PARIS VOLLEY;0530012;LAVAL 53;3/1;25-20,20-25,25-22,25-18;95-85;Gymnase Coubertin;12345;DUPONT Jean;;;67890;DURAND Paul\n"
    ).encode("latin-1")

    service = MatchService(ctx)
    synced = service.sync_entity_matches(entite_code="LIIDF", csv_bytes=csv_content)

    assert len(synced) == 1
    match_db = synced[0]
    assert match_db.code_match == "R1M001"
    assert match_db.poule_id == poule.id
    assert match_db.equipe_a.club_id == club_a.id
    assert match_db.equipe_b.club_id == club_b.id
    assert match_db.sets_equipe_a == 3
    assert match_db.sets_equipe_b == 1
    assert len(match_db.arbitrages) == 2


# ═════════════════════════════════════════════════════════════════════════════
# 7. Tests Pipeline Orchestrator End-to-End
# ═════════════════════════════════════════════════════════════════════════════

def test_orchestrator_end_to_end(test_session, monkeypatch):
    ctx = PipelineContext(session=test_session, saison="2024/2025")
    orchestrator = PipelineOrchestrator(ctx=ctx)

    # Mock entity scraper HTML
    sample_entities_html = """
    <select name="sel_entites">
        <option value="ABCCS">FFVB Nationale</option>
    </select>
    """
    monkeypatch.setattr(
        orchestrator.entity_service.scraper,
        "fetch_entities_page_html",
        lambda: sample_entities_html,
    )

    # Mock club scraper HTML
    sample_clubs_html = """
    <table>
        <tr>
            <td>0750001</td>
            <td>PARIS VOLLEY</td>
            <td>Ligue IDF</td>
            <td>CD 75</td>
        </tr>
    </table>
    """
    monkeypatch.setattr(
        orchestrator.club_service.scraper,
        "fetch_clubs_html",
        lambda: sample_clubs_html,
    )

    # Mock competition scraper HTML
    sample_comps_html = """
    <div class="compet_title">Championnat Elite</div>
    <a href="vbspo_calendrier.php?poule=EMA">Poule A</a>
    """
    monkeypatch.setattr(
        orchestrator.comp_service.comp_scraper,
        "fetch_home_html",
        lambda entite_code, saison: sample_comps_html,
    )

    # Mock match scraper CSV
    sample_matches_csv = (
        "Entite;Journee;Match;Date;Heure;EQA_no;EQA_nom;EQB_no;EQB_nom;Set;Score;Total;Salle;Arb1_Lic;Arb1_Nom\n"
        "ABCCS;1;EMA001;15/10/2024;20h00;0750001;PARIS VOLLEY;;TOURCOING;3/0;25-20,25-21,25-22;75-63;Charpy;;\n"
    ).encode("latin-1")
    monkeypatch.setattr(
        orchestrator.match_service.scraper,
        "fetch_export_csv",
        lambda entite_code, saison, poule=None: sample_matches_csv,
    )

    # Run orchestrator
    stats = orchestrator.run(entity_codes=["ABCCS"])

    assert stats.entities_synced >= 1
    assert stats.clubs_synced == 1
    assert stats.competitions_created == 1
    assert stats.poules_created == 1
    assert stats.matches_created == 1
    assert stats.errors_count == 0
