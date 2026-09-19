"""Tests de non-régression pour l'unicité des matchs inter-entités, l'idempotence du scraping et la fin de boucle de parsing."""

from datetime import date
from sqlalchemy import select

from pyvolley.database.export_import_service import ExportImportService
from pyvolley.database.import_service import MatchImportService
from pyvolley.database.models import MatchDB, CompetitionDB
from pyvolley.scrapers.ffvb.export_scraper import ExportMatchInfo
from pyvolley.core.models import Match as CoreMatch, Equipe as CoreEquipe


def test_same_code_match_across_different_competitions(test_session):
    """Vérifie que deux matchs avec le même code_match dans deux compétitions distinctes coexistent sans conflit."""
    service_idf = ExportImportService(test_session)
    match_idf = ExportMatchInfo(
        code_match="MMF013",
        saison="2022/2023",
        entite_code="LIIDF",
        competition_nom="PRE REGIONALE MASCULINE",
        competition_groupe="PRM",
        poule_code="PRMA",
        genre="MASCULIN",
        categorie_age="SENIOR",
        equipe_a_nom="PARIS VOLLEY",
        equipe_b_nom="VINCENNES VOLLEY",
        date_match=date(2022, 10, 15),
    )
    stats1 = service_idf.import_matches([match_idf], "LIIDF", "2022/2023")
    test_session.commit()
    assert stats1["errors"] == 0
    assert stats1["imported"] == 1

    service_lor = ExportImportService(test_session)
    match_lor = ExportMatchInfo(
        code_match="MMF013",
        saison="2022/2023",
        entite_code="LLORR",
        competition_nom="REGIONALE 1 MASCULINE",
        competition_groupe="R1M",
        poule_code="R1MA",
        genre="MASCULIN",
        categorie_age="SENIOR",
        equipe_a_nom="METZ VOLLEY",
        equipe_b_nom="NANCY VOLLEY",
        date_match=date(2022, 10, 22),
    )
    stats2 = service_lor.import_matches([match_lor], "LLORR", "2022/2023")
    test_session.commit()
    assert stats2["errors"] == 0
    assert stats2["imported"] == 1

    # Les deux matchs doivent coexister en base de données
    matches = test_session.scalars(
        select(MatchDB).where(MatchDB.code_match == "MMF013")
    ).all()
    assert len(matches) == 2
    comp_ids = {m.competition_id for m in matches}
    assert len(comp_ids) == 2


def test_re_scraping_identical_matches_yields_duplicates(test_session):
    """Vérifie que re-scraper des données identiques classe 100% des matchs en doublons/inchangés."""
    service1 = ExportImportService(test_session)
    match1 = ExportMatchInfo(
        code_match="TCA001",
        saison="2023/2024",
        entite_code="ABCCS",
        competition_nom="ELITE MASCULINE",
        competition_groupe="EMA",
        poule_code="EMA",
        genre="MASCULIN",
        categorie_age="SENIOR",
        equipe_a_nom="Club Alpha",
        equipe_b_nom="Club Beta",
        date_match=date(2023, 11, 4),
        match_joue=True,
        score_sets="3/1",
        sets=[(25, 20), (23, 25), (25, 18), (25, 22)],
    )
    stats1 = service1.import_matches([match1], "ABCCS", "2023/2024")
    test_session.commit()
    assert stats1["imported"] == 1
    assert stats1["updated"] == 0
    assert stats1["duplicates"] == 0

    # Deuxième import avec exactement les mêmes données
    service2 = ExportImportService(test_session)
    stats2 = service2.import_matches([match1], "ABCCS", "2023/2024")
    test_session.commit()
    assert stats2["imported"] == 0
    assert stats2["updated"] == 0
    assert stats2["duplicates"] == 1


def test_re_scraping_parsed_match_does_not_reset_status_or_score(test_session):
    """Vérifie qu'un match déjà parsé ne voit pas son statut repasser à 'discovered' lors d'un re-scrape."""
    service = ExportImportService(test_session)
    match_info = ExportMatchInfo(
        code_match="PARSED01",
        saison="2023/2024",
        entite_code="ABCCS",
        competition_nom="ELITE FEMININE",
        competition_groupe="EFA",
        poule_code="EFA",
        genre="FEMININ",
        categorie_age="SENIOR",
        equipe_a_nom="Club A",
        equipe_b_nom="Club B",
        date_match=date(2023, 10, 1),
        match_joue=True,
        score_sets="3/0",
    )
    service.import_matches([match_info], "ABCCS", "2023/2024")
    test_session.commit()

    # Simuler le passage du match à l'état "parsed"
    match_db = test_session.scalars(
        select(MatchDB).where(MatchDB.code_match == "PARSED01")
    ).one()
    match_db.parsing_status = "parsed"
    match_db.score_pdf = "3-0"
    test_session.commit()

    # Re-scrape identique
    service_rescrape = ExportImportService(test_session)
    stats = service_rescrape.import_matches([match_info], "ABCCS", "2023/2024")
    test_session.commit()

    assert stats["duplicates"] == 1
    assert stats["updated"] == 0

    # Vérifier que le statut n'a pas été altéré
    test_session.refresh(match_db)
    assert match_db.parsing_status == "parsed"
    assert match_db.score_pdf == "3-0"


def test_pdf_parse_without_delta_marks_match_as_parsed(test_session):
    """Vérifie qu'un match au statut 'downloaded' passe à 'parsed' même si le PDF n'apporte pas de nouveau delta."""
    # Créer le match initialement découvert / téléchargé
    service_export = ExportImportService(test_session)
    match_info = ExportMatchInfo(
        code_match="NODELTA01",
        saison="2023/2024",
        entite_code="ABCCS",
        competition_nom="COUPE DE FRANCE",
        competition_groupe="CDF",
        poule_code="CDFA",
        genre="MASCULIN",
        categorie_age="SENIOR",
        equipe_a_nom="Club X",
        equipe_b_nom="Club Y",
        date_match=date(2023, 12, 1),
        match_joue=True,
        score_sets="3/0",
    )
    service_export.import_matches([match_info], "ABCCS", "2023/2024")
    test_session.commit()

    match_db = test_session.scalars(
        select(MatchDB).where(MatchDB.code_match == "NODELTA01")
    ).one()
    match_db.parsing_status = "downloaded"
    test_session.commit()

    # Enrichir avec un objet CoreMatch sans stats additionnelles
    import_service = MatchImportService(test_session)
    core_match = CoreMatch(
        code_match="NODELTA01",
        date=date(2023, 12, 1),
        equipe_a=CoreEquipe(nom="Club X", joueurs=[], liberos=[]),
        equipe_b=CoreEquipe(nom="Club Y", joueurs=[], liberos=[]),
        sets=[],
    )

    enriched = import_service.enrich_from_pdf(match_db, core_match)
    test_session.commit()

    # Le match ne doit pas être resté en 'downloaded' (qui causerait une boucle infinie de re-parsing)
    assert match_db.parsing_status == "parsed"
