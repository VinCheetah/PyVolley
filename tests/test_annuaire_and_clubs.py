import pytest
from unittest.mock import patch, MagicMock
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from pyvolley.database.models import Base, LigueDB, ComiteDB, ClubDB, SalleClubDB
from pyvolley.scrapers.ffvb.annuaire_scraper import (
    AnnuaireScraper,
    AnnuaireLigueInfo,
    AnnuaireComiteInfo,
    AnnuaireClubInfo,
    AnnuaireFicheClub,
    parse_ligue_annuaire_html,
    parse_club_fiche_html,
)
from pyvolley.database.annuaire_service import AnnuaireService
from pyvolley.api.routes.map import _club_popup


HTML_LIGUE_SAMPLE = """
<html>
<body>
<table>
  <tr>
    <td class="titreblanc_gd">Ligue ILE DE FRANCE</td>
  </tr>
  <tr>
    <td class="liengris_pt">Tél :</td>
    <td>01 40 00 00 00</td>
  </tr>
  <tr>
    <td class="liengris_pt">Président :</td>
    <td>M. PRESIDENT LIGUE</td>
  </tr>
  <tr>
    <td><a href="mailto:ligue@volley-idf.fr">Email</a></td>
  </tr>
  <!-- Comite -->
  <tr>
    <td class="liensuite4_gd" align="center">075</td>
    <td class="liensuite4_gd">PARIS</td>
    <td><a href="mailto:comite75@volley.fr">Mail</a></td>
    <td><a href="http://comite75.fr">Web</a></td>
  </tr>
  <!-- Club -->
  <tr>
    <td class="lienquestion" align="center">0750001</td>
    <td class="lienquestion">PARIS VOLLEY CLUB</td>
    <td><a href="mailto:contact@parisvolley.fr">Mail</a></td>
    <td><a href="http://parisvolley.fr">Web</a></td>
  </tr>
</table>
</body>
</html>
"""

HTML_FICHE_SAMPLE = """
<html>
<body>
<table>
  <tr><td class="lienblanc_pt">Coordonnées</td></tr>
  <tr>
    <td>Téléphone :</td><td>01 23 45 67 89</td>
  </tr>
  <tr>
    <td><a href="mailto:contact@parisvolley.fr">Mail</a></td>
  </tr>
</table>
<table>
  <tr><td class="lienblanc_pt">Siège Social</td></tr>
  <tr><td class="lienquestion">10 RUE DU VOLLEY</td></tr>
  <tr><td class="lienquestion">75013 PARIS</td></tr>
</table>
<table>
  <tr><td class="lienblanc_pt">Dirigeants</td></tr>
  <tr><td class="lienquestion">M. JEAN DUPONT</td></tr>
</table>
<table>
  <tr><td class="lienblanc_pt">Correspondant</td></tr>
  <tr><td class="lienquestion">Mme DUPONT</td></tr>
</table>
</body>
</html>
"""


def test_parse_ligue_annuaire_html():
    ligue_info, comites, clubs = parse_ligue_annuaire_html(
        HTML_LIGUE_SAMPLE,
        ligue_code="13",
        default_ligue_nom="ILE-DE-FRANCE",
    )

    assert ligue_info.nom == "ILE DE FRANCE"
    assert ligue_info.telephone == "01 40 00 00 00"
    assert ligue_info.president == "M. PRESIDENT LIGUE"
    assert ligue_info.email == "ligue@volley-idf.fr"

    assert len(comites) == 1
    c = comites[0]
    assert c.code == "075"
    assert c.nom == "PARIS"
    assert c.numero_departement == "75"
    assert c.email == "comite75@volley.fr"

    assert len(clubs) == 1
    cl = clubs[0]
    assert cl.code_ffvb == "0750001"
    assert cl.nom == "PARIS VOLLEY CLUB"
    assert cl.comite_code == "075"
    assert cl.email == "contact@parisvolley.fr"


def test_parse_club_fiche_html():
    fiche = parse_club_fiche_html(HTML_FICHE_SAMPLE, code_ffvb="0750001")

    assert fiche.code_ffvb == "0750001"
    assert fiche.adresse_siege == "10 RUE DU VOLLEY"
    assert fiche.code_postal_siege == "75013"
    assert fiche.ville_siege == "PARIS"
    assert fiche.telephone == "01 23 45 67 89"
    assert fiche.email == "contact@parisvolley.fr"


def test_annuaire_service_sync_and_relational_hierarchy():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()

    mock_scraper = MagicMock(spec=AnnuaireScraper)
    ligues = [AnnuaireLigueInfo(code="13", nom="ILE-DE-FRANCE")]
    comites = [AnnuaireComiteInfo(code="075", nom="PARIS", numero_departement="75", ligue_code="13")]
    clubs = [
        AnnuaireClubInfo(
            code_ffvb="0750001",
            nom="PARIS VOLLEY CLUB",
            ligue_code="13",
            comite_code="075",
            email="contact@parisvolley.fr",
        )
    ]
    mock_scraper.scrape_all_ligues.return_value = (ligues, comites, clubs)
    mock_scraper.fetch_club_fiche.return_value = AnnuaireFicheClub(
        code_ffvb="0750001",
        nom="PARIS VOLLEY CLUB",
        adresse_siege="10 RUE DU VOLLEY",
        code_postal_siege="75013",
        ville_siege="PARIS",
        president="M. JEAN DUPONT",
    )

    service = AnnuaireService(session=session, scraper=mock_scraper)

    # Mock geocode_addresses_batch
    fake_geo_res = MagicMock()
    fake_geo_res.latitude = 48.83
    fake_geo_res.longitude = 2.36

    with patch("pyvolley.database.annuaire_service.geocode_addresses_batch") as mock_geo:
        mock_geo.return_value = {"club_0750001": fake_geo_res}

        summary = service.sync_annuaire(
            geocode=True,
            fetch_details=True,
            max_workers=1,
        )

    assert summary["ligues_synced"] == 1
    assert summary["comites_synced"] == 1
    assert summary["clubs_created"] == 1
    assert summary["clubs_geocoded"] == 1

    # Check database integrity and relationships
    club_db = session.query(ClubDB).filter_by(code_ffvb="0750001").first()
    assert club_db is not None
    assert club_db.nom == "PARIS VOLLEY CLUB"
    assert club_db.adresse_siege == "10 RUE DU VOLLEY"
    assert club_db.code_postal_siege == "75013"
    assert club_db.ville_siege == "PARIS"
    assert club_db.latitude == 48.83
    assert club_db.longitude == 2.36

    # Verify relational links
    assert club_db.ligue_rel is not None
    assert club_db.ligue_rel.code == "13"
    assert club_db.ligue_rel.nom == "ILE-DE-FRANCE"

    assert club_db.comite_rel is not None
    assert club_db.comite_rel.code == "075"
    assert club_db.comite_rel.nom == "PARIS"

    # Verify reverse relationships
    assert len(club_db.ligue_rel.clubs) == 1
    assert len(club_db.comite_rel.clubs) == 1


def test_club_marker_strictly_uses_siege_social():
    """Verify club popup and coordinates are strictly based on siège social."""
    club = ClubDB(
        id=42,
        code_ffvb="0750001",
        nom="PARIS VOLLEY CLUB",
        ville="PARIS",
        adresse_siege="10 RUE DU VOLLEY",
        code_postal_siege="75013",
        ville_siege="PARIS",
        latitude=48.83,
        longitude=2.36,
    )
    salle = SalleClubDB(
        id=1,
        club_id=42,
        numero=1,
        nom="Gymnase Charpy",
        adresse="Avenue Pierre de Coubertin",
        ville="Paris",
        latitude=48.82,
        longitude=2.37,
    )
    club.salles = [salle]

    # The club's coordinates should remain 48.83 / 2.36 (its headquarters)
    # and not be hijacked by Charpy (48.82 / 2.37)
    assert club.latitude == 48.83
    assert club.longitude == 2.36

    popup = _club_popup(club)
    assert "PARIS VOLLEY CLUB" in popup
    assert "Club · Siège Social" in popup
    assert "10 RUE DU VOLLEY" in popup
    assert "75013 PARIS" in popup
    assert "/clubs/0750001" in popup


def test_cli_init_clubs_help():
    """Verify CLI pyvolley init-clubs --help runs successfully."""
    from typer.testing import CliRunner
    from pyvolley.cli.main import app

    runner = CliRunner()
    result = runner.invoke(app, ["init-clubs", "--help"])
    assert result.exit_code == 0
    assert "Initialiser ou synchroniser" in result.output
    assert "--geocode" in result.output
    assert "--no-geocode" in result.output


def test_geostats_relationships_with_ligue_and_comite():
    """Verify GeoStatsDB connects cleanly to LigueDB and ComiteDB."""
    from pyvolley.database.models import GeoStatsDB, SaisonDB

    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()

    saison = SaisonDB(code="2025-2026", nom="Saison 2025-2026")
    ligue = LigueDB(code="13", nom="ILE-DE-FRANCE")
    comite = ComiteDB(code="075", nom="PARIS", numero_departement="75", ligue=ligue)
    session.add_all([saison, ligue, comite])
    session.flush()

    geo_stat = GeoStatsDB(
        saison_id=saison.id,
        echelon="departement",
        code_territoire="75",
        nom_territoire="Paris",
        ligue_id=ligue.id,
        comite_id=comite.id,
        nb_clubs=45,
    )
    session.add(geo_stat)
    session.commit()

    saved = session.query(GeoStatsDB).first()
    assert saved is not None
    assert saved.ligue is not None
    assert saved.ligue.nom == "ILE-DE-FRANCE"
    assert saved.comite is not None
    assert saved.comite.nom == "PARIS"

