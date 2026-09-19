"""Tests pour la gestion différenciée et prioritaire des scores Scraper vs Parser.

Vérifie :
1. La prévalence du score scraper sur le score parser en cas de divergence.
2. La conservation des scores globaux et du détail des sets des deux sources.
3. L'attribution des points et du gagnant de compétition basée sur le scraper.
4. Le calcul normal des statistiques de jeu des joueurs basé sur le déroulé du parser.
5. La détection et les helpers d'affichage de la divergence sur les modèles MatchDB et Match.
"""

from datetime import date
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from pyvolley.shared.match_scores import resolve_match_score
from pyvolley.database.models import (
    Base,
    SaisonDB,
    CompetitionDB,
    EquipeDB,
    ClubDB,
    MatchDB,
    SetDB,
    ParticipationMatchDB,
    JoueurDB,
    FormationDB,
)
from pyvolley.database.import_service import MatchImportService
from pyvolley.database.repositories import MatchRepository
from pyvolley.analysis.classement import MatchData, calculer_classement
from pyvolley.core.models import (
    Match,
    Equipe,
    Set,
    SetTeamData,
    Formation,
    Joueur,
)


def test_resolve_match_score_scraper_priority():
    """Vérifie que l'export (scraper) prévaut sur le PDF en cas de conflit."""
    # Conflit : Scraper 3/1 vs PDF 3/2
    res = resolve_match_score(score_export="3/1", score_pdf="3/2")
    assert res.conflict is True
    assert res.score_effective == "3/1"
    assert res.primary_source == "export"
    assert res.secondary_source == "pdf"
    assert "Scrape 3/1" in res.score_display
    assert "PDF 3/2" in res.score_display

    # Seul l'export est présent
    res_export = resolve_match_score(score_export="3/0", score_pdf=None)
    assert res_export.conflict is False
    assert res_export.score_effective == "3/0"
    assert res_export.primary_source == "export"

    # Seul le PDF est présent
    res_pdf = resolve_match_score(score_export=None, score_pdf="3/0")
    assert res_pdf.conflict is False
    assert res_pdf.score_effective == "3/0"
    assert res_pdf.primary_source == "pdf"


def test_match_models_score_divergence_properties():
    """Vérifie les propriétés et helpers de divergence sur MatchDB et Match core."""
    match_core = Match(
        code_match="TEST_DIV_01",
        score_export="3/1",
        score_pdf="3/2",
        sets_detail_export=[
            {"numero": 1, "score_a": 25, "score_b": 20},
            {"numero": 2, "score_a": 22, "score_b": 25},
            {"numero": 3, "score_a": 25, "score_b": 18},
            {"numero": 4, "score_a": 25, "score_b": 21},
        ],
        sets=[
            Set(numero=1, score_a=25, score_b=20),
            Set(numero=2, score_a=22, score_b=25),
            Set(numero=3, score_a=25, score_b=18),
            Set(numero=4, score_a=23, score_b=25),
            Set(numero=5, score_a=15, score_b=13),
        ],
    )

    assert match_core.score_effective == "3/1"
    assert match_core.sets_detail_export_display == "25-20, 22-25, 25-18, 25-21"
    assert match_core.sets_detail_pdf_display == "25-20, 22-25, 25-18, 23-25, 15-13"
    assert match_core.score_conflict is True

    div = match_core.score_divergence
    assert div["has_divergence"] is True
    assert div["score_sets_divergent"] is True
    assert div["sets_detail_divergent"] is True
    assert div["score_scraper"] == "3/1"
    assert div["score_parser"] == "3/2"


def test_enrich_from_pdf_preserves_scraper_score_and_detail():
    """Vérifie que lors de enrich_from_pdf, le score et le vainqueur du scraper prévalent."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()

    saison = SaisonDB(code="2024-2025", date_debut=date(2024, 9, 1), date_fin=date(2025, 6, 30))
    session.add(saison)

    comp = CompetitionDB(code_competition="REG_M", nom="Régionale Masculine", saison=saison)
    session.add(comp)

    club_a = ClubDB(nom="PARIS VOLLEY", code_ffvb="0750001")
    club_b = ClubDB(nom="TOURS VB", code_ffvb="0370001")
    session.add_all([club_a, club_b])
    session.flush()

    eq_a = EquipeDB(nom="PARIS 1", club_id=club_a.id)
    eq_b = EquipeDB(nom="TOURS 1", club_id=club_b.id)
    session.add_all([eq_a, eq_b])
    session.flush()

    # Match initialisé par le scraper
    sets_scraper = [
        {"numero": 1, "score_a": 25, "score_b": 20},
        {"numero": 2, "score_a": 22, "score_b": 25},
        {"numero": 3, "score_a": 25, "score_b": 18},
        {"numero": 4, "score_a": 25, "score_b": 21},
    ]
    match_db = MatchDB(
        code_match="PMAA001",
        saison_id=saison.id,
        competition_id=comp.id,
        equipe_a_id=eq_a.id,
        equipe_b_id=eq_b.id,
        score_export="3/1",
        score_sets="3/1",
        sets_equipe_a=3,
        sets_equipe_b=1,
        sets_detail_export=sets_scraper,
        vainqueur="PARIS 1",
        match_joue=True,
        parsing_status="discovered",
    )
    session.add(match_db)
    session.commit()

    # Données issues du PDF (qui indique un score différent, ex: 3/2 en faveur de Tours)
    joueur_a1 = Joueur(licence="111111", nom="DUPONT", prenom="Jean", numero="7")
    joueur_b1 = Joueur(licence="222222", nom="DURAND", prenom="Paul", numero="10")

    parsed_match = Match(
        code_match="PMAA001",
        equipe_a=Equipe(nom="PARIS 1", joueurs=[joueur_a1]),
        equipe_b=Equipe(nom="TOURS 1", joueurs=[joueur_b1]),
        score_final="2/3",
        sets_a=2,
        sets_b=3,
        vainqueur_nom="TOURS 1",
        match_joue=True,
        sets=[
            Set(
                numero=1, score_a=25, score_b=20,
                equipe_a=SetTeamData(formation=Formation(position_1="7", position_2="7", position_3="7", position_4="7", position_5="7", position_6="7")),
                equipe_b=SetTeamData(formation=Formation(position_1="10", position_2="10", position_3="10", position_4="10", position_5="10", position_6="10")),
            ),
            Set(numero=2, score_a=22, score_b=25),
            Set(numero=3, score_a=25, score_b=18),
            Set(numero=4, score_a=20, score_b=25),
            Set(numero=5, score_a=13, score_b=15),
        ],
    )

    import_service = MatchImportService(session)
    res = import_service.enrich_from_pdf(match_db, parsed_match)
    session.commit()

    assert res is True
    # 1. Le score du scraper prévaut pour la compétition
    assert match_db.score_sets == "3/1"
    assert match_db.sets_equipe_a == 3
    assert match_db.sets_equipe_b == 1
    assert match_db.vainqueur == "PARIS 1"

    # 2. Les deux scores sont bien enregistrés
    assert match_db.score_export == "3/1"
    assert match_db.score_pdf == "2/3"

    # 3. Le détail des sets du scraper est intact
    assert match_db.sets_detail_export == sets_scraper
    assert match_db.sets_detail_export_display == "25-20, 22-25, 25-18, 25-21"

    # 4. Les sets détaillés du parser sont bien présents dans SetDB pour les stats joueurs
    assert len(match_db.sets) == 5
    assert match_db.sets[0].score_a == 25 and match_db.sets[0].score_b == 20
    assert match_db.sets[4].score_a == 13 and match_db.sets[4].score_b == 15

    # 5. La divergence est détectée
    assert match_db.score_conflict is True
    assert match_db.score_divergence["has_divergence"] is True

    # 6. Vérification du classement de compétition :
    # CompetitionRepository.get_matchs_for_classement utilise les données du scraper
    from pyvolley.database.repositories import CompetitionRepository
    comp_repo = CompetitionRepository(session)
    matchs_classement = comp_repo.get_matchs_for_classement(comp.id)
    assert len(matchs_classement) == 1
    m_cls = matchs_classement[0]
    assert m_cls.sets_a == 3
    assert m_cls.sets_b == 1
    # Somme des points du scraper : 25+22+25+25 = 97 pour A, 20+25+18+21 = 84 pour B
    assert m_cls.points_a == 97
    assert m_cls.points_b == 84

    # Le classement FFVB attribue 3 points à l'équipe A (victoire 3-1) et 0 point à l'équipe B
    lignes = calculer_classement(matchs_classement)
    assert len(lignes) == 2
    ligne_paris = next(l for l in lignes if l.equipe_nom == "PARIS 1")
    ligne_tours = next(l for l in lignes if l.equipe_nom == "TOURS 1")
    assert ligne_paris.points == 3
    assert ligne_paris.victoires == 1
    assert ligne_tours.points == 0
    assert ligne_tours.defaites == 1

    # 7. Vérification des statistiques de jeu des joueurs :
    # Les stats sont calculées normalement sur le déroulé du parser PDF
    from pyvolley.database.player_stats_service import JoueurMatchStatsService
    stats_service = JoueurMatchStatsService(session)
    count = stats_service.compute_and_store_for_match(match_db, force=True)
    assert count >= 1
    stats_a, stats_b = stats_service.get_match_stats_grouped(match_db.id)
    assert len(stats_a) >= 1
    assert stats_a[0]["stats"]["sets_joues"] >= 1
