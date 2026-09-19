"""Tests de non-régression pour l'unicité des compétitions lors de l'import."""

import pytest
from sqlalchemy import select

from pyvolley.database.export_import_service import ExportImportService
from pyvolley.database.models import CompetitionDB, MatchDB
from pyvolley.scrapers.ffvb.export_scraper import ExportMatchInfo


def test_competition_uniqueness_cfc_mixed_categories(test_session):
    """Vérifie que des matches CFC avec ou sans categorie_age ne provoquent pas d'IntegrityError."""
    service = ExportImportService(test_session)

    match1 = ExportMatchInfo(
        code_match="CFC001",
        saison="2020/2021",
        entite_code="ABCCS",
        competition_nom="COUPE DE FRANCE FEMININE",
        competition_groupe="CFC",
        poule_code="CFC",
        genre="FEMININ",
        categorie_age="SENIOR",
        equipe_a_nom="Club A",
        equipe_b_nom="Club B",
    )

    match2 = ExportMatchInfo(
        code_match="CFC002",
        saison="2020/2021",
        entite_code="ABCCS",
        competition_nom="CFC",
        competition_groupe="CFC",
        poule_code="CFC",
        genre="FEMININ",
        categorie_age=None,  # Pas de categorie explicite
        equipe_a_nom="Club C",
        equipe_b_nom="Club D",
    )

    stats = service.import_matches([match1, match2], "ABCCS", "2020/2021")
    test_session.commit()

    assert stats["errors"] == 0
    assert stats["imported"] == 2

    comps = test_session.scalars(
        select(CompetitionDB).where(CompetitionDB.nom == "CFC")
    ).all()
    assert len(comps) == 1
    assert comps[0].genre == "FEMININ"
    assert comps[0].categorie == "SENIOR"


def test_competition_uniqueness_across_entities(test_session):
    """Vérifie l'import sur plusieurs entités partageant une même compétition."""
    service1 = ExportImportService(test_session)

    match1 = ExportMatchInfo(
        code_match="CFC101",
        saison="2020/2021",
        entite_code="FEDE",
        competition_nom="CFC",
        competition_groupe="CFC",
        poule_code="CFC",
        genre="FEMININ",
        categorie_age=None,
        equipe_a_nom="Equipe 1",
        equipe_b_nom="Equipe 2",
    )
    stats1 = service1.import_matches([match1], "FEDE", "2020/2021")
    test_session.commit()
    assert stats1["errors"] == 0

    # Deuxième entité avec sa propre instance de service
    service2 = ExportImportService(test_session)
    match2 = ExportMatchInfo(
        code_match="CFC102",
        saison="2020/2021",
        entite_code="LIGUE",
        competition_nom="CFC",
        competition_groupe="CFC",
        poule_code="CFC",
        genre="FEMININ",
        categorie_age="SENIOR",
        equipe_a_nom="Equipe 3",
        equipe_b_nom="Equipe 4",
    )
    stats2 = service2.import_matches([match2], "LIGUE", "2020/2021")
    test_session.commit()
    assert stats2["errors"] == 0

    comps = test_session.scalars(
        select(CompetitionDB).where(CompetitionDB.nom == "CFC").order_by(CompetitionDB.id)
    ).all()
    assert len(comps) == 2
    assert comps[0].entite_id != comps[1].entite_id


def test_competition_uniqueness_none_first(test_session):
    """Vérifie que si un match sans catégorie arrive en premier, le second avec SENIOR ne provoque pas d'erreur."""
    service = ExportImportService(test_session)

    match1 = ExportMatchInfo(
        code_match="CFC201",
        saison="2020/2021",
        entite_code="ABCCS",
        competition_nom="CFC",
        competition_groupe="CFC",
        poule_code="CFC",
        genre="FEMININ",
        categorie_age=None,
        equipe_a_nom="Club A",
        equipe_b_nom="Club B",
    )

    match2 = ExportMatchInfo(
        code_match="CFC202",
        saison="2020/2021",
        entite_code="ABCCS",
        competition_nom="COUPE DE FRANCE FEMININE",
        competition_groupe="CFC",
        poule_code="CFC",
        genre="FEMININ",
        categorie_age="SENIOR",
        equipe_a_nom="Club C",
        equipe_b_nom="Club D",
    )

    stats = service.import_matches([match1, match2], "ABCCS", "2020/2021")
    test_session.commit()

    assert stats["errors"] == 0
    assert stats["imported"] == 2

    comps = test_session.scalars(
        select(CompetitionDB).where(CompetitionDB.nom == "CFC")
    ).all()
    assert len(comps) == 1
    assert comps[0].categorie == "SENIOR"

