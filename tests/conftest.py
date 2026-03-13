"""
Fixtures pytest partagées pour tous les tests.
"""

import pytest
from datetime import date, time
from pathlib import Path
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from pyvolley.database.models import Base
from pyvolley.core.models import (
    Match, Equipe, Joueur, Set, SetTeamData, Formation,
    Changement, TimeOut, Arbitre, Sanction, Officiel,
    RoleArbitre, TypeSanction,
)


# ============== Fixtures Database ==============

@pytest.fixture(scope="function")
def test_engine():
    """Crée un engine SQLite en mémoire pour les tests."""
    engine = create_engine("sqlite:///:memory:", echo=False)
    Base.metadata.create_all(engine)
    yield engine
    Base.metadata.drop_all(engine)


@pytest.fixture(scope="function")
def test_session(test_engine):
    """Crée une session de test."""
    Session = sessionmaker(bind=test_engine)
    session = Session()
    yield session
    session.rollback()
    session.close()


# ============== Fixtures Data ==============

@pytest.fixture
def sample_joueur():
    """Crée un joueur exemple."""
    return Joueur(
        numero="7",
        nom="DUPONT",
        prenom="Jean",
        licence="123456789",
        est_capitaine=True,
    )


@pytest.fixture
def sample_equipe(sample_joueur):
    """Crée une équipe exemple."""
    return Equipe(
        nom="AS Volley Club",
        joueurs=[sample_joueur],
        liberos=[],
    )


@pytest.fixture
def sample_set():
    """Crée un set exemple."""
    return Set(
        numero=1,
        score_a=25,
        score_b=23,
    )


@pytest.fixture
def sample_match(sample_equipe, sample_set):
    """Crée un match exemple."""
    equipe_b = Equipe(
        nom="BC Volley Team",
        joueurs=[],
        liberos=[],
    )

    return Match(
        ligue="Île de France",
        competition="Championnat Régional",
        code_match="2024-R1-001",
        journee="1",
        lieu="Paris",
        salle="Gymnase Central",
        equipe_a=sample_equipe,
        equipe_b=equipe_b,
        sets=[sample_set],
        vainqueur_nom="AS Volley Club",
        score_final="3-0",
        duree_totale="1h30",
        arbitres=[],
        sanctions=[],
        remarques="",
    )


@pytest.fixture
def full_match():
    """Crée un match complet avec toutes les entités pour les tests d'import."""
    joueurs_a = [
        Joueur(numero="1", nom="DUPONT", prenom="Jean", licence="100001", est_capitaine=True),
        Joueur(numero="4", nom="MARTIN", prenom="Paul", licence="100002"),
        Joueur(numero="7", nom="DURAND", prenom="Luc", licence="100003"),
        Joueur(numero="9", nom="PETIT", prenom="Marc", licence="100004"),
        Joueur(numero="11", nom="ROBERT", prenom="Hugo", licence="100005"),
        Joueur(numero="13", nom="RICHARD", prenom="Tom", licence="100006"),
    ]
    lib_a = Joueur(numero="2", nom="MOREL", prenom="Alex", licence="100007", est_libero=True)
    joueurs_b = [
        Joueur(numero="3", nom="SIMON", prenom="Julien", licence="200001", est_capitaine=True),
        Joueur(numero="5", nom="LEROY", prenom="David", licence="200002"),
        Joueur(numero="8", nom="ROUX", prenom="Pierre", licence="200003"),
        Joueur(numero="10", nom="MOREAU", prenom="Louis", licence="200004"),
        Joueur(numero="12", nom="FOURNIER", prenom="Felix", licence="200005"),
        Joueur(numero="14", nom="GIRARD", prenom="Emile", licence="200006"),
    ]
    lib_b = Joueur(numero="6", nom="BONNET", prenom="Theo", licence="200007", est_libero=True)

    equipe_a = Equipe(
        nom="AS Volley Paris",
        joueurs=joueurs_a + [lib_a],
        liberos=[lib_a],
        officiels=[
            Officiel(role="EA", nom="COACH_A", prenom="Alice", licence="998877"),
        ],
    )
    equipe_b = Equipe(
        nom="BC Volley Lyon",
        joueurs=joueurs_b + [lib_b],
        liberos=[lib_b],
        officiels=[
            Officiel(role="EB", nom="COACH_B", prenom="Bob", licence=None),
        ],
    )

    set1 = Set(
        numero=1,
        score_a=25,
        score_b=22,
        duree_minutes=28,
        service_initial="A",
        equipe_a=SetTeamData(
            formation=Formation(
                position_1="1", position_2="4", position_3="7",
                position_4="9", position_5="11", position_6="13",
            ),
            changements=[Changement(joueur_entrant="2", joueur_sortant="13", score_a=15, score_b=12)],
            timeouts=[TimeOut(score_a=8, score_b=10)],
        ),
        equipe_b=SetTeamData(
            formation=Formation(
                position_1="3", position_2="5", position_3="8",
                position_4="10", position_5="12", position_6="14",
            ),
            changements=[],
            timeouts=[TimeOut(score_a=20, score_b=18)],
        ),
    )
    set2 = Set(
        numero=2,
        score_a=25,
        score_b=20,
        duree_minutes=25,
        service_initial="B",
    )
    set3 = Set(
        numero=3,
        score_a=25,
        score_b=18,
        duree_minutes=22,
        service_initial="A",
    )

    return Match(
        code_match="TST-FULL-001",
        date=date(2025, 1, 15),
        heure=time(20, 0),
        lieu="Paris",
        salle="Gymnase Central",
        competition="EMA - ELITE MASCULINE - POULE A",
        competition_code="EMA",
        saison="2024-2025",
        journee="5",
        equipe_a=equipe_a,
        equipe_b=equipe_b,
        sets=[set1, set2, set3],
        vainqueur_nom="AS Volley Paris",
        score_final="3-0",
        sets_a=3,
        sets_b=0,
        duree_totale="1h15",
        match_joue=True,
        has_details=True,
        arbitres=[
            Arbitre(nom="ARBITRE1", prenom="Pierre", licence="ARB001", role=RoleArbitre.PREMIER),
            Arbitre(nom="ARBITRE2", prenom="Marie", licence="ARB002", role=RoleArbitre.SECOND),
        ],
        sanctions=[
            Sanction(type=TypeSanction.AVERTISSEMENT, set_numero=2, equipe="B", joueur_numero="5", score_a=15, score_b=10),
        ],
        remarques="Match test complet",
        source_pdf="2024-2025/LIRA/TST-FULL-001.pdf",
    )


# ============== Fixtures Files ==============

@pytest.fixture
def test_data_dir():
    """Retourne le chemin vers le dossier de données de test."""
    return Path(__file__).parent / "data"


@pytest.fixture
def sample_pdf_path(test_data_dir):
    """Retourne le chemin vers un PDF de test (s'il existe)."""
    pdf_dir = test_data_dir / "pdfs"
    if pdf_dir.exists():
        pdfs = list(pdf_dir.glob("*.pdf"))
        if pdfs:
            return pdfs[0]
    return None


# ============== Fixtures API ==============

@pytest.fixture
def api_client():
    """Crée un client de test pour l'API FastAPI."""
    from fastapi.testclient import TestClient
    from pyvolley.api.app import app

    return TestClient(app)


@pytest.fixture
def web_client():
    """Crée un client de test pour l'application web."""
    from fastapi.testclient import TestClient
    from pyvolley.web.app import web_app

    return TestClient(web_app)
