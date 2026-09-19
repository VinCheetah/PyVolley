"""Tests d'isolation des compétitions et matchs par entité organisatrice."""

from datetime import date
from sqlalchemy import select

from pyvolley.database.export_import_service import ExportImportService
from pyvolley.database.models import CompetitionDB, MatchDB, PouleDB
from pyvolley.scrapers.ffvb.export_scraper import ExportMatchInfo


def test_entities_with_same_poule_and_match_code_do_not_collide(test_session):
    """Vérifie que deux entités distinctes ayant le même code de poule et le même

    code de match créent 2 compétitions et 2 matchs distincts sans écrasement (~0 mis à jour).
    Scénario réel : PTIDF78 et LIIDF partagent tous deux la poule '6OA' et le match '6OA002'.
    """
    saison = "2024/2025"

    # 1. Import entité 1 (Comité Yvelines PTIDF78)
    service_78 = ExportImportService(test_session)
    match_78 = ExportMatchInfo(
        code_match="6OA002",
        saison=saison,
        entite_code="PTIDF78",
        competition_nom="6OA",
        competition_groupe=None,  # Fallback sur poule_code '6OA'
        poule_code="6OA",
        genre="MASCULIN",
        categorie_age="SENIOR",
        equipe_a_nom="Velizy",
        equipe_b_nom="Chevreuse 2",
        club_a_code_ffvb="0785001",
        club_b_code_ffvb="0785002",
        date_match=date(2024, 10, 5),
        match_joue=True,
        score_sets="3/0",
    )
    stats_78 = service_78.import_matches([match_78], "PTIDF78", saison)
    test_session.commit()

    assert stats_78["errors"] == 0
    assert stats_78["imported"] == 1
    assert stats_78["updated"] == 0
    assert stats_78["duplicates"] == 0

    # 2. Import entité 2 (Ligue IDF LIIDF) après coup
    service_idf = ExportImportService(test_session)
    match_idf = ExportMatchInfo(
        code_match="6OA002",
        saison=saison,
        entite_code="LIIDF",
        competition_nom="6OA",
        competition_groupe=None,  # Fallback sur poule_code '6OA'
        poule_code="6OA",
        genre="MASCULIN",
        categorie_age="SENIOR",
        equipe_a_nom="SAND SYSTEM ASSOCIATION 1",
        equipe_b_nom="FS VAL D'EUROPE ESBLY 1",
        club_a_code_ffvb="0755003",
        club_b_code_ffvb="0775004",
        date_match=date(2024, 10, 12),
        match_joue=True,
        score_sets="1/3",
    )
    stats_idf = service_idf.import_matches([match_idf], "LIIDF", saison)
    test_session.commit()

    # Le match LIIDF NE DOIT PAS être considéré comme 'mis à jour'
    assert stats_idf["errors"] == 0
    assert stats_idf["imported"] == 1
    assert stats_idf["updated"] == 0
    assert stats_idf["duplicates"] == 0

    # 3. Vérifier que 2 compétitions distinctes existent
    comps = test_session.scalars(
        select(CompetitionDB).where(CompetitionDB.nom == "6OA").order_by(CompetitionDB.id)
    ).all()
    assert len(comps) == 2
    assert comps[0].entite_id != comps[1].entite_id

    # 4. Vérifier que 2 matchs distincts coexistent en base avec leurs équipes respectives
    matches = test_session.scalars(
        select(MatchDB).where(MatchDB.code_match == "6OA002").order_by(MatchDB.id)
    ).all()
    assert len(matches) == 2
    assert matches[0].competition_id != matches[1].competition_id
    assert matches[0].club_a_code_ffvb == "0785001"
    assert matches[1].club_a_code_ffvb == "0755003"
    assert matches[0].score_sets == "3/0"
    assert matches[1].score_sets == "1/3"


def test_generic_competition_groupe_isolated_by_entity(test_session):
    """Vérifie que deux ligues ayant un groupe générique identique

    (ex: 'CHAMPIONNAT REGIONAL M13 FEMININS') créent des compétitions séparées.
    """
    saison = "2024/2025"
    comp_groupe = "CHAMPIONNAT REGIONAL M13 FEMININS"

    # Ligue Bretagne
    service_br = ExportImportService(test_session)
    match_br = ExportMatchInfo(
        code_match="BFAA001",
        saison=saison,
        entite_code="LIBR",
        competition_nom=comp_groupe,
        competition_groupe=comp_groupe,
        poule_code="BFA",
        genre="FEMININ",
        categorie_age="M13",
        equipe_a_nom="Rennes Volley",
        equipe_b_nom="Vannes Volley",
        club_a_code_ffvb="0350001",
        club_b_code_ffvb="0560001",
        match_joue=True,
        score_sets="2/0",
    )
    stats_br = service_br.import_matches([match_br], "LIBR", saison)
    test_session.commit()
    assert stats_br["imported"] == 1
    assert stats_br["updated"] == 0

    # Ligue Rhône-Alpes
    service_ra = ExportImportService(test_session)
    match_ra = ExportMatchInfo(
        code_match="BFAA001",
        saison=saison,
        entite_code="LIRA",
        competition_nom=comp_groupe,
        competition_groupe=comp_groupe,
        poule_code="BFA",
        genre="FEMININ",
        categorie_age="M13",
        equipe_a_nom="VB Villefranche",
        equipe_b_nom="VC Meximieux",
        club_a_code_ffvb="0693332",
        club_b_code_ffvb="0015366",
        match_joue=True,
        score_sets="2/1",
    )
    stats_ra = service_ra.import_matches([match_ra], "LIRA", saison)
    test_session.commit()
    assert stats_ra["imported"] == 1
    assert stats_ra["updated"] == 0

    # Les deux compétitions doivent être distinctes
    comps = test_session.scalars(
        select(CompetitionDB).where(CompetitionDB.nom == comp_groupe)
    ).all()
    assert len(comps) == 2


def test_collision_guard_refuses_destructive_overwrite(test_session):
    """Vérifie que le garde-fou empêche l'écrasement silencieux d'un match si les clubs sont différents."""
    saison = "2024/2025"
    service = ExportImportService(test_session)

    match1 = ExportMatchInfo(
        code_match="TEST001",
        saison=saison,
        entite_code="TESTENT",
        competition_nom="COMP TEST",
        competition_groupe="COMP TEST",
        poule_code="TESTA",
        genre="MASCULIN",
        categorie_age="SENIOR",
        equipe_a_nom="Equipe 1",
        equipe_b_nom="Equipe 2",
        club_a_code_ffvb="0010001",
        club_b_code_ffvb="0010002",
        match_joue=True,
        score_sets="3/0",
    )
    stats1 = service.import_matches([match1], "TESTENT", saison)
    test_session.commit()
    assert stats1["imported"] == 1

    # Tenter d'importer dans la même compétition un match avec même code mais clubs incompatibles
    match2 = ExportMatchInfo(
        code_match="TEST001",
        saison=saison,
        entite_code="TESTENT",
        competition_nom="COMP TEST",
        competition_groupe="COMP TEST",
        poule_code="TESTA",
        genre="MASCULIN",
        categorie_age="SENIOR",
        equipe_a_nom="Equipe Totalement Autre",
        equipe_b_nom="Equipe Inconnue",
        club_a_code_ffvb="0999999",  # Club différent !
        club_b_code_ffvb="0888888",
        match_joue=True,
        score_sets="0/3",
    )
    stats2 = service.import_matches([match2], "TESTENT", saison)
    test_session.commit()

    # Doit refuser l'écrasement (updated == 0)
    assert stats2["updated"] == 0
    assert stats2["duplicates"] == 1

    # Le match initial est resté intact
    m = test_session.scalars(select(MatchDB).where(MatchDB.code_match == "TEST001")).one()
    assert m.club_a_code_ffvb == "0010001"
    assert m.score_sets == "3/0"
