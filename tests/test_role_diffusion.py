"""Tests pour le service de diffusion réseau multi-passes (RoleDiffusionService)."""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from pyvolley.database.models import (
    Base,
    MatchDB,
    EquipeDB,
    JoueurDB,
    ParticipationMatchDB,
    SetDB,
    FormationDB,
    SaisonDB,
    CompetitionDB,
    JoueurMatchStatsDB,
)
from pyvolley.database.role_diffusion_service import RoleDiffusionService


@pytest.fixture
def memory_db_session():
    """Crée une base SQLite en mémoire avec le schéma complet."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


def test_role_diffusion_service_convergence(memory_db_session):
    """Vérifie que la diffusion multi-passes converge et propage les rôles."""
    session = memory_db_session

    saison = SaisonDB(code="2025-2026", nom="Saison 2025-2026")
    session.add(saison)
    session.flush()

    comp = CompetitionDB(code_competition="REG-M", nom="Regionale M", saison_id=saison.id)
    eq_a = EquipeDB(nom="Equipe Alpha")
    eq_b = EquipeDB(nom="Equipe Beta")
    session.add_all([comp, eq_a, eq_b])
    session.flush()

    # Créer 7 joueurs pour l'équipe Alpha
    joueurs = []
    for i in range(1, 8):
        j = JoueurDB(nom=f"Nom{i}", prenom=f"Prenom{i}", licence=f"LIC00{i}")
        joueurs.append(j)
    session.add_all(joueurs)
    session.flush()

    # Créer 2 matchs
    for m_idx in range(1, 3):
        m = MatchDB(
            code_match=f"MATCH-00{m_idx}",
            saison_id=saison.id,
            competition_id=comp.id,
            equipe_a_id=eq_a.id,
            equipe_b_id=eq_b.id,
            match_joue=True,
            has_details=True,
        )
        session.add(m)
        session.flush()

        # Participations
        for num, j in enumerate(joueurs, start=1):
            is_lib = (num == 7)
            pm = ParticipationMatchDB(
                match_id=m.id,
                joueur_id=j.id,
                equipe_id=eq_a.id,
                numero_maillot=str(num),
                side="A",
                est_libero=is_lib,
            )
            jms = JoueurMatchStatsDB(
                match_id=m.id,
                joueur_id=j.id,
                equipe_id=eq_a.id,
                role_principal=None,
                role_confiance=0.0,
            )
            session.add_all([pm, jms])

        # Set avec rotation standard
        s = SetDB(
            match_id=m.id,
            numero=1,
            score_a=25,
            score_b=20,
        )
        session.add(s)
        session.flush()

        f = FormationDB(
            set_id=s.id,
            equipe="A",
            position_1="1",
            position_2="2",
            position_3="3",
            position_4="4",
            position_5="5",
            position_6="6",
        )
        session.add(f)
        session.flush()

    session.commit()

    service = RoleDiffusionService(session)
    report = service.run_diffusion(max_iterations=3, commit=True)

    assert report.total_matches == 2
    assert report.total_players == 7
    assert report.iterations_run >= 1
    assert report.average_final_confidence > 0.40
    # Vérifier que le libéro a été reconnu
    assert "LIBERO" in report.final_role_distribution or "Libéro" in report.final_role_distribution
