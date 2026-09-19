"""Tests for FFVB links, data provenance, and template URL helpers."""

from datetime import date
import pytest
from starlette.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from pyvolley.web.app import create_web_app
from pyvolley.api.dependencies import get_session
from pyvolley.database.models import (
    Base,
    JoueurDB,
    EquipeDB,
    ClubDB,
    CompetitionDB,
    PouleDB,
    SaisonDB,
    EntiteFFVBDB,
    MatchDB,
    ArbitreDB,
    ArbitreMatchDB,
    OfficielMatchDB,
    ParticipationMatchDB,
    JoueurMatchStatsDB,
)
from pyvolley.web.templateconfig import (
    path_for_entity,
    _extract_canonical_val,
    ffvb_fdme_url,
    ffvb_poule_calendrier_url,
    ffvb_poule_classement_url,
    ffvb_poule_export_csv_url,
    ffvb_entite_home_url,
    ffvb_annuaire_url,
)


def test_extract_canonical_val_handles_dicts_and_objects():
    """Verify _extract_canonical_val extracts canonical attributes from dicts and objects."""
    # From model objects
    joueur = JoueurDB(id=1, licence="123456", nom="Test")
    assert str(_extract_canonical_val(joueur, ("licence", "id"))) == "123456"

    # From dictionaries
    d_joueur = {"licence": "654321", "nom": "TestDict"}
    assert str(_extract_canonical_val(d_joueur, ("licence", "id"))) == "654321"

    d_joueur_id = {"id": 99, "nom": "TestOnlyId"}
    assert str(_extract_canonical_val(d_joueur_id, ("licence", "id"))) == "99"

    # Scalar values
    assert str(_extract_canonical_val("777888", ("licence", "id"))) == "777888"
    assert str(_extract_canonical_val(42, ("licence", "id"))) == "42"

    # Dict without matching keys should NOT stringify the entire dict
    empty_dict = {"foo": "bar"}
    assert _extract_canonical_val(empty_dict, ("licence", "id")) is None


def test_path_for_entity_dictionary_handling():
    """Ensure path_for_entity does not return dictionary string representations in URLs."""
    # Dict with canonical keys
    assert path_for_entity("joueur", {"licence": "LIC999"}) == "/joueurs/LIC999"
    assert path_for_entity("club", {"code_ffvb": "075001"}) == "/clubs/075001"
    assert path_for_entity("match", {"code_match": "M101"}) == "/matchs/M101"
    assert path_for_entity("competition", {"code_competition": "COMP01"}) == "/competitions/COMP01"
    assert path_for_entity("poule", {"code": "POULE_A"}) == "/poules/POULE_A"
    assert path_for_entity("arbitre", {"licence": "ARB01"}) == "/arbitres/ARB01"
    assert path_for_entity("entraineur", {"id": 12}) == "/entraineurs/12"
    assert path_for_entity("equipe", {"id": 44}) == "/equipes/44"

    # Fallback to id
    assert path_for_entity("joueur", {"id": 10}) == "/joueurs/10"
    assert path_for_entity("club", {"id": 20}) == "/clubs/20"
    assert path_for_entity("match", {"id": 30}) == "/matchs/30"


def test_ffvb_url_helpers():
    """Test the FFVB URL helper functions."""
    entite = EntiteFFVBDB(id=1, code="ABCS", nom="Fédération")
    saison = SaisonDB(id=1, code="2024-2025")
    comp = CompetitionDB(id=1, code_competition="COMP01", entite=entite, saison=saison)
    poule = PouleDB(id=1, code="EMA", competition=comp)

    # ffvb_fdme_url
    match = MatchDB(
        id=1,
        code_match="NAT001",
        poule=poule,
        saison=saison,
    )
    url = ffvb_fdme_url(match)
    assert "ffvolley_fdme.php" in url
    assert "codent=ABCS" in url
    assert "codmatch=NAT001" in url

    # ffvb_poule_calendrier_url and classement
    cal_url = ffvb_poule_calendrier_url(poule)
    assert "vbspo_calendrier.php" in cal_url
    assert "calend=COMPLET" in cal_url
    assert "poule=EMA" in cal_url

    class_url = ffvb_poule_classement_url(poule)
    assert "vbspo_calendrier.php" in class_url
    assert "poule=EMA" in class_url

    # ffvb_poule_export_csv_url (scraper CSV source)
    csv_url = ffvb_poule_export_csv_url(poule)
    assert "vbspo_calendrier_export.php" in csv_url
    assert "calend=COMPLET" in csv_url
    assert "poule=EMA" in csv_url

    # ffvb_entite_home_url
    home_url = ffvb_entite_home_url("ABCS", "2024-2025")
    assert "vbspo_home.php" in home_url
    assert "codent=ABCS" in home_url

    # ffvb_annuaire_url
    annuaire_with_club = ffvb_annuaire_url(ClubDB(code_ffvb="075001"))
    assert "rech_aff_club.php?num_affil=075001" in annuaire_with_club

    annuaire_generic = ffvb_annuaire_url()
    assert "rech_aff_club.php" in annuaire_generic


@pytest.fixture
def web_test_client():
    """Setup an in-memory SQLite database and TestClient for web routes."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    TestingSessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    session = TestingSessionLocal()

    saison = SaisonDB(code="2024-2025", nom="Saison 2024-2025")
    club = ClubDB(nom="Volley Club Paris", code_ffvb="0750001", ville="Paris")
    entite = EntiteFFVBDB(code="ABCS", nom="Fédération")
    session.add_all([saison, club, entite])
    session.flush()

    competition = CompetitionDB(
        nom="Nationale 2 M",
        code_competition="NAT2M",
        niveau="NATIONALE_2",
        saison_id=saison.id,
        entite_id=entite.id,
    )
    session.add(competition)
    session.flush()

    poule = PouleDB(code="EMA", nom="Poule A", competition_id=competition.id)
    poule_b = PouleDB(code="EMB", nom="Poule B", competition_id=competition.id)
    session.add_all([poule, poule_b])
    session.flush()

    equipe_a = EquipeDB(nom="Paris Volley 1", club_id=club.id)
    equipe_b = EquipeDB(nom="Lyon Volley", club_id=club.id)
    joueur = JoueurDB(nom="DUPONT", prenom="Jean", licence="0987654")
    arbitre = ArbitreDB(nom="MARTIN", prenom="Claire", licence="ARB12345")
    session.add_all([equipe_a, equipe_b, joueur, arbitre])
    session.flush()

    match = MatchDB(
        code_match="NAT042",
        date_match=date(2025, 3, 15),
        saison_id=saison.id,
        competition_id=competition.id,
        poule_id=poule.id,
        equipe_a_id=equipe_a.id,
        equipe_b_id=equipe_b.id,
        sets_equipe_a=3,
        sets_equipe_b=2,
        score_sets="3/2",
        match_joue=True,
    )
    session.add(match)
    session.flush()

    part = ParticipationMatchDB(
        match_id=match.id,
        joueur_id=joueur.id,
        equipe_id=equipe_a.id,
        numero_maillot="10",
    )
    stats = JoueurMatchStatsDB(
        match_id=match.id,
        joueur_id=joueur.id,
        equipe_id=equipe_a.id,
        points_gagnes=18,
        sets_joues=5,
    )
    arb_match = ArbitreMatchDB(
        match_id=match.id,
        arbitre_id=arbitre.id,
        role="1er Arbitre",
    )
    ent_match = OfficielMatchDB(
        match_id=match.id,
        nom="BERNARD",
        prenom="Paul",
        licence="COACH01",
        role="EA",
        equipe="A",
    )
    session.add_all([part, stats, arb_match, ent_match])
    session.commit()

    def override_get_session():
        db = TestingSessionLocal()
        try:
            yield db
        finally:
            db.close()

    app = create_web_app()
    app.dependency_overrides[get_session] = override_get_session
    client = TestClient(app, raise_server_exceptions=True)
    yield client
    session.close()


def test_web_provenance_and_enriched_links(web_test_client):
    """Verify data provenance banners, FFVB external links, and internal navigation."""
    client = web_test_client

    # 1. Poule detail has provenance banner and FFVB scraper CSV export link
    res_poule = client.get("/poules/EMA")
    assert res_poule.status_code == 200
    assert "Provenance des données" in res_poule.text
    assert "vbspo_calendrier_export.php" in res_poule.text
    assert "Source Scraper (CSV)" in res_poule.text

    # 2. Competition detail has provenance banner and poule action links
    res_comp = client.get("/competitions/NAT2M")
    assert res_comp.status_code == 200
    assert "Source officielle FFVB" in res_comp.text
    assert "/poules/EMA" in res_comp.text
    assert "vbspo_calendrier_export.php" in res_comp.text

    # 3. Match detail has FDME link and poule link
    res_match = client.get("/matchs/NAT042")
    assert res_match.status_code == 200
    assert "ffvolley_fdme.php" in res_match.text
    assert "/poules/EMA" in res_match.text
    assert "/equipes/" in res_match.text

    # 4. Club detail has official Annuaire FFVB link
    res_club = client.get("/clubs/0750001")
    assert res_club.status_code == 200
    assert "rech_aff_club.php?num_affil=0750001" in res_club.text

    # 5. Entraineurs list and detail
    res_ent_list = client.get("/entraineurs")
    assert res_ent_list.status_code == 200
    assert "BERNARD" in res_ent_list.text
    assert "/entraineurs/" in res_ent_list.text
    assert "Profil" in res_ent_list.text

    res_ent_detail = client.get("/entraineurs/COACH01")
    assert res_ent_detail.status_code == 200
    assert "BERNARD" in res_ent_detail.text
    assert "/matchs/NAT042" in res_ent_detail.text

    # 6. Arbitres list and detail
    res_arb_list = client.get("/arbitres")
    assert res_arb_list.status_code == 200
    assert "MARTIN" in res_arb_list.text
    assert "Profil" in res_arb_list.text

    res_arb_detail = client.get("/arbitres/ARB12345")
    assert res_arb_detail.status_code == 200
    assert "MARTIN" in res_arb_detail.text
    assert "/matchs/NAT042" in res_arb_detail.text

    # 7. Equipe detail has poule link and official FFVB poule buttons
    res_eq = client.get("/equipes/1")
    assert res_eq.status_code == 200
    assert "/poules/EMA" in res_eq.text
    assert "Classement FFVB" in res_eq.text
    assert "Calendrier FFVB" in res_eq.text

    # 8. Joueur detail has match rows with FDME link
    res_j = client.get("/joueurs/0987654")
    assert res_j.status_code == 200
    assert "/matchs/NAT042" in res_j.text
    assert "ffvolley_fdme.php" in res_j.text

    # 9. Territoire has interactive carte and clubs directory links
    res_terr = client.get("/territoire")
    assert res_terr.status_code == 200
    assert "/carte" in res_terr.text
