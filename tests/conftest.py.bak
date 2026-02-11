"""
Fixtures pytest partagées pour tous les tests.
"""

import pytest
from pathlib import Path
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from pyvolley.database.models import Base
from pyvolley.core.models import Match, Equipe, Joueur, Set


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
