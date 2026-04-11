"""
Tests pour le scraper adressier FFVB et l'enrichissement des clubs.

Couvre :
- Parsing CSV de l'adressier (parse_adressier_csv)
- Construction d'URLs (adressier, club planning, club classement)
- Import et enrichissement des clubs en base de données
"""

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from pyvolley.database.models import Base, ClubDB, SalleClubDB, SetDB, EquipeDB
from pyvolley.database.export_import_service import ExportImportService
from pyvolley.scrapers.ffvb.adressier_scraper import (
    AdressierClubInfo,
    SalleInfo,
    parse_adressier_csv,
    build_adressier_url,
    build_club_planning_url,
    build_club_classement_url,
    _clean,
    _clean_address,
    _parse_capacite,
    _parse_salle,
)


# =====================================================================
# Fixtures
# =====================================================================

@pytest.fixture
def adressier_engine():
    """Engine SQLite en mémoire pour les tests adressier."""
    engine = create_engine("sqlite:///:memory:", echo=False)
    Base.metadata.create_all(engine)
    yield engine
    Base.metadata.drop_all(engine)


@pytest.fixture
def adressier_session(adressier_engine):
    """Session de test pour l'adressier."""
    Session = sessionmaker(bind=adressier_engine)
    session = Session()
    yield session
    session.rollback()
    session.close()


def _build_csv(rows: list[str], header: str | None = None) -> bytes:
    """Construit un CSV d'adressier à partir de lignes."""
    default_header = (
        "Entite;Poule;NClub;NomClub;Ligue;Pos.;Couleurs;Pdt;Entr.;Adj.;"
        "Correspondant;Co_Adr1;Co_Adr2;Co_Adr3;Co_Ville;Co_Tel;Co_Port;Co_Mail;"
        "S1_Nom;S1_Adr1;S1_Adr2;S1_Adr3;S1_Ville;S1_Tel;S1_Sol;S1_Cap;S1_Trsp;"
        "S2_Nom;S2_Adr1;S2_Adr2;S2_Adr3;S2_Ville;S2_Tel;S2_Sol;S2_Cap;S2_Trsp;\n"
    )
    h = header or default_header
    content = h + "\n".join(rows)
    return content.encode("windows-1252")


# Mapping nom de champ → index de colonne (0-based)
_COL_MAP = {
    "entite": 0, "poule": 1, "nclub": 2, "nom_club": 3,
    "ligue": 4, "position": 5, "couleurs": 6,
    "president": 7, "entraineur": 8, "adjoint": 9,
    "correspondant": 10, "co_adr1": 11, "co_adr2": 12, "co_adr3": 13,
    "co_ville": 14, "co_tel": 15, "co_port": 16, "co_mail": 17,
    "s1_nom": 18, "s1_adr1": 19, "s1_adr2": 20, "s1_adr3": 21,
    "s1_ville": 22, "s1_tel": 23, "s1_sol": 24, "s1_cap": 25, "s1_trsp": 26,
    "s2_nom": 27, "s2_adr1": 28, "s2_adr2": 29, "s2_adr3": 30,
    "s2_ville": 31, "s2_tel": 32, "s2_sol": 33, "s2_cap": 34, "s2_trsp": 35,
}


def _row(**kwargs) -> str:
    """Construit une ligne CSV avec les champs aux bons indices."""
    cols = [""] * 36
    for key, val in kwargs.items():
        cols[_COL_MAP[key]] = str(val)
    return ";".join(cols) + ";"


# =====================================================================
# Tests des utilitaires
# =====================================================================

class TestClean:
    """Tests de la fonction _clean."""

    def test_normal(self):
        assert _clean("  GRENOBLE  ") == "GRENOBLE"

    def test_empty(self):
        assert _clean("") is None

    def test_whitespace_only(self):
        assert _clean("   ") is None

    def test_none_like(self):
        assert _clean(None) is None


class TestCleanAddress:
    """Tests de la construction d'adresses."""

    def test_all_parts(self):
        assert _clean_address("1 RUE A", "BAT B", "ETAGE 3") == "1 RUE A, BAT B, ETAGE 3"

    def test_some_empty(self):
        assert _clean_address("1 RUE A", "", "38400 VILLE") == "1 RUE A, 38400 VILLE"

    def test_all_empty(self):
        assert _clean_address("", "", "") is None

    def test_single_part(self):
        assert _clean_address("10 RUE X", "", "") == "10 RUE X"


class TestParseCapacite:
    """Tests du parsing de la capacité."""

    def test_valid(self):
        assert _parse_capacite("2000") == 2000

    def test_zero(self):
        assert _parse_capacite("0") is None

    def test_empty(self):
        assert _parse_capacite("") is None

    def test_invalid(self):
        assert _parse_capacite("abc") is None

    def test_whitespace(self):
        assert _parse_capacite("  500  ") == 500


# =====================================================================
# Tests de parse_adressier_csv
# =====================================================================

class TestParseAdressierCsv:
    """Tests du parsing CSV de l'adressier."""

    def test_club_complet(self):
        """Parse un club avec toutes les données remplies."""
        row = (
            "ABCCS;EMA;0622126;HARNES VOLLEY-BALL;Ligue HAUTS-DE-FRANCE;1;"
            "ROUGE ET NOIR;M. BECQUERIAUX ARNAUD;M. ONDRUSEK ROMAN;;"
            "M. SNOECK BERTRAND;16 RUE DE LA SOMME;;;62790 LEFOREST;"
            "07.66.06.33.11;;contact@harnes-volleyball.fr;"
            "SALLE REGIONALE;128 CHEMIN VALOIS;;;62440 HARNES;"
            "07.66.06.33.11;taraflex bicolore;2000;TGV (Lens/Lille);"
            "SALLE ANDRE BIGOTTE;AVENUE DES SAULES;;;62440 HARNES;"
            "03.21.20.51.47;taraflex;700;TGV (Lens/Lille);"
        )
        result = parse_adressier_csv(_build_csv([row]))

        assert len(result) == 1
        club = result[0]
        assert club.code_ffvb == "0622126"
        assert club.nom == "HARNES VOLLEY-BALL"
        assert club.ligue == "Ligue HAUTS-DE-FRANCE"
        assert club.poule == "EMA"
        assert club.position == 1
        assert club.couleurs == "ROUGE ET NOIR"
        assert club.president == "M. BECQUERIAUX ARNAUD"
        assert club.entraineur == "M. ONDRUSEK ROMAN"
        assert club.correspondant_nom == "M. SNOECK BERTRAND"
        assert club.correspondant_adresse == "16 RUE DE LA SOMME"
        assert club.correspondant_ville == "62790 LEFOREST"
        assert club.correspondant_email == "contact@harnes-volleyball.fr"

        # Salles
        assert len(club.salles) == 2
        s1 = club.salles[0]
        assert s1.numero == 1
        assert s1.nom == "SALLE REGIONALE"
        assert s1.adresse == "128 CHEMIN VALOIS"
        assert s1.ville == "62440 HARNES"
        assert s1.sol == "taraflex bicolore"
        assert s1.capacite == 2000
        assert s1.transport == "TGV (Lens/Lille)"

        s2 = club.salles[1]
        assert s2.numero == 2
        assert s2.nom == "SALLE ANDRE BIGOTTE"
        assert s2.capacite == 700

    def test_club_minimal(self):
        """Parse un club avec seulement les champs obligatoires."""
        row = _row(
            entite="ABCCS", poule="2FA", nclub="0136082",
            nom_club="VITROLLES SPORTS VB", ligue="Ligue PACA",
            position="3", couleurs="BLEU",
        )
        result = parse_adressier_csv(_build_csv([row]))

        assert len(result) == 1
        club = result[0]
        assert club.code_ffvb == "0136082"
        assert club.nom == "VITROLLES SPORTS VB"
        assert club.ligue == "Ligue PACA"
        assert club.president is None
        assert club.correspondant_email is None
        assert len(club.salles) == 0

    def test_multiple_clubs(self):
        """Parse plusieurs clubs."""
        rows = [
            _row(
                entite="ABCCS", poule="EMA", nclub="0622126",
                nom_club="HARNES VB", ligue="Ligue HDF", position="1",
                couleurs="ROUGE", s1_nom="SALLE A", s1_adr1="RUE A", s1_ville="VILLE A",
            ),
            _row(
                entite="ABCCS", poule="EMA", nclub="0382201",
                nom_club="GRENOBLE VUC", ligue="Ligue ARA", position="2",
                couleurs="BLEU", s1_nom="SALLE B", s1_adr1="RUE B", s1_ville="VILLE B",
            ),
        ]
        result = parse_adressier_csv(_build_csv(rows))
        assert len(result) == 2
        assert result[0].code_ffvb == "0622126"
        assert result[1].code_ffvb == "0382201"

    def test_csv_vide(self):
        """CSV vide retourne une liste vide."""
        result = parse_adressier_csv(b"")
        assert result == []

    def test_header_seul(self):
        """CSV avec seulement l'en-tête retourne une liste vide."""
        result = parse_adressier_csv(_build_csv([]))
        assert result == []

    def test_ligne_incomplete(self):
        """Ligne avec trop peu de colonnes est ignorée."""
        row = "ABCCS;EMA;0622126"  # Seulement 3 colonnes
        result = parse_adressier_csv(_build_csv([row]))
        assert result == []

    def test_sans_code_club(self):
        """Ligne sans code club est ignorée."""
        row = _row(
            entite="ABCCS", poule="EMA", nclub="",
            nom_club="CLUB SANS CODE", ligue="Ligue X",
            position="1", couleurs="BLEU",
        )
        result = parse_adressier_csv(_build_csv([row]))
        assert result == []

    def test_une_seule_salle(self):
        """Club avec une seule salle (S2 vide)."""
        row = _row(
            entite="ABCCS", poule="EMA", nclub="0622126",
            nom_club="CLUB TEST", ligue="Ligue", position="1", couleurs="VERT",
            s1_nom="GYMNASE", s1_adr1="RUE X", s1_ville="VILLE X",
            s1_tel="01.02.03", s1_sol="parquet", s1_cap="500", s1_trsp="bus",
        )
        result = parse_adressier_csv(_build_csv([row]))
        assert len(result) == 1
        assert len(result[0].salles) == 1
        assert result[0].salles[0].nom == "GYMNASE"

    def test_salle_capacite_zero(self):
        """Salle avec capacité 0 → None."""
        row = _row(
            entite="ABCCS", poule="EMA", nclub="0622126",
            nom_club="CLUB", ligue="Ligue", position="1",
            s1_nom="SALLE", s1_adr1="RUE", s1_ville="VILLE",
            s1_sol="bois", s1_cap="0", s1_trsp="train",
        )
        result = parse_adressier_csv(_build_csv([row]))
        assert len(result[0].salles) == 1
        assert result[0].salles[0].capacite is None

    def test_encodage_special(self):
        """Gère les caractères spéciaux (accents, etc.)."""
        row = _row(
            entite="ABCCS", poule="EFA", nclub="0750001",
            nom_club="PARIS SAINT-GERMAIN VB", ligue="Ligue IDF",
            position="1", couleurs="BLEU ET ROUGE",
            president="M. DUPONT René",
            correspondant="M. MÜLLER André",
            co_adr1="1 RUE DES CHAMPS-ÉLYSÉES", co_ville="75008 PARIS",
            co_mail="info@psgvb.fr",
            s1_nom="PALAIS DES SPORTS", s1_adr1="AV PORTE DE VERSAILLES",
            s1_ville="75015 PARIS", s1_sol="taraflex", s1_cap="3000",
            s1_trsp="métro",
        )
        data = _build_csv([row])
        result = parse_adressier_csv(data)
        assert len(result) == 1
        assert "PARIS SAINT-GERMAIN" in result[0].nom

    def test_adresse_correspondant_multilignes(self):
        """Adresse avec les 3 champs remplis."""
        row = _row(
            entite="ABCCS", poule="EMA", nclub="0622126",
            nom_club="CLUB", ligue="Ligue", position="1", couleurs="ROUGE",
            correspondant="M. X",
            co_adr1="16 RUE A", co_adr2="BAT B", co_adr3="ETAGE 3",
            co_ville="75000 PARIS", co_tel="01.00", co_port="06.00",
            co_mail="a@b.fr",
        )
        result = parse_adressier_csv(_build_csv([row]))
        assert result[0].correspondant_adresse == "16 RUE A, BAT B, ETAGE 3"


# =====================================================================
# Tests de construction d'URLs
# =====================================================================

class TestBuildUrls:
    """Tests des constructeurs d'URLs."""

    def test_build_adressier_url_from_resu(self):
        url = build_adressier_url("https://www.ffvbbeach.org/ffvbapp/resu/")
        assert url == "https://www.ffvbbeach.org/ffvbapp/adressier/adressier_pdf.php"

    def test_build_adressier_url_no_trailing_slash(self):
        url = build_adressier_url("https://www.ffvbbeach.org/ffvbapp/resu")
        assert url == "https://www.ffvbbeach.org/ffvbapp/adressier/adressier_pdf.php"

    def test_build_club_planning_url(self):
        url = build_club_planning_url(
            "https://www.ffvbbeach.org/ffvbapp/resu/",
            "ABCCS", "0622126",
        )
        assert "planning_club.php" in url
        assert "codent=ABCCS" in url
        assert "cnclub=0622126" in url

    def test_build_club_classement_url(self):
        url = build_club_classement_url(
            "https://www.ffvbbeach.org/ffvbapp/resu/",
            "ABCCS", "2025/2026", "0622126",
        )
        assert "planning_club_class.php" in url
        assert "codent=ABCCS" in url
        assert "cnclub=0622126" in url
        assert "2025" in url


# =====================================================================
# Tests d'enrichissement des clubs en base
# =====================================================================

class TestEnrichClubs:
    """Tests de l'enrichissement des clubs via l'adressier."""

    def test_enrich_existing_club(self, adressier_session):
        """Enrichit un club qui existe déjà en base."""
        # Créer le club en base (comme le ferait import_matches)
        club = ClubDB(nom="HARNES VB", code_ffvb="0622126")
        adressier_session.add(club)
        adressier_session.flush()

        service = ExportImportService(adressier_session)
        clubs_info = [
            AdressierClubInfo(
                code_ffvb="0622126",
                nom="HARNES VOLLEY-BALL",
                ligue="Ligue HAUTS-DE-FRANCE",
                couleurs="ROUGE ET NOIR",
                president="M. BECQUERIAUX ARNAUD",
                entraineur="M. ONDRUSEK ROMAN",
                correspondant_nom="M. SNOECK BERTRAND",
                correspondant_adresse="16 RUE DE LA SOMME",
                correspondant_ville="62790 LEFOREST",
                correspondant_email="contact@harnes-volleyball.fr",
                salles=[
                    SalleInfo(
                        numero=1,
                        nom="SALLE REGIONALE",
                        adresse="128 CHEMIN VALOIS",
                        ville="62440 HARNES",
                        sol="taraflex",
                        capacite=2000,
                    ),
                    SalleInfo(
                        numero=2,
                        nom="SALLE BIGOTTE",
                        adresse="AVE DES SAULES",
                        ville="62440 HARNES",
                        sol="taraflex",
                        capacite=700,
                    ),
                ],
            )
        ]

        stats = service.enrich_clubs(
            clubs_info, "ABCCS", "2025/2026",
            "https://www.ffvbbeach.org/ffvbapp/resu/",
        )

        assert stats["enriched"] == 1
        assert stats["created"] == 0

        # Vérifier les données du club
        club = adressier_session.execute(
            select(ClubDB).where(ClubDB.code_ffvb == "0622126")
        ).scalar_one()
        assert club.nom == "HARNES VOLLEY-BALL"
        assert club.ligue == "Ligue HAUTS-DE-FRANCE"
        assert club.couleurs == "ROUGE ET NOIR"
        assert club.president == "M. BECQUERIAUX ARNAUD"
        assert club.correspondant_email == "contact@harnes-volleyball.fr"
        assert club.ville == "LEFOREST"
        assert club.departement == "62"

        # Vérifier les salles
        salles = adressier_session.execute(
            select(SalleClubDB).where(SalleClubDB.club_id == club.id)
        ).scalars().all()
        assert len(salles) == 2
        s1 = [s for s in salles if s.numero == 1][0]
        assert s1.nom == "SALLE REGIONALE"
        assert s1.capacite == 2000

    def test_enrich_creates_new_club(self, adressier_session):
        """Crée un nouveau club s'il n'existe pas en base."""
        service = ExportImportService(adressier_session)
        clubs_info = [
            AdressierClubInfo(
                code_ffvb="0999999",
                nom="NOUVEAU CLUB VB",
                ligue="Ligue TEST",
                couleurs="VERT",
            )
        ]

        stats = service.enrich_clubs(
            clubs_info, "ABCCS", "2025/2026",
            "https://www.ffvbbeach.org/ffvbapp/resu/",
        )

        assert stats["created"] == 1
        assert stats["enriched"] == 0

        club = adressier_session.execute(
            select(ClubDB).where(ClubDB.code_ffvb == "0999999")
        ).scalar_one()
        assert club.nom == "NOUVEAU CLUB VB"
        assert club.couleurs == "VERT"

    def test_enrich_infers_nom_court_from_teams(self, adressier_session):
        """Infère nom_court depuis les équipes associées au club."""
        club = ClubDB(nom="ASSOCIATION SPORTIVE VOLLEY TEST", code_ffvb="0123000")
        adressier_session.add(club)
        adressier_session.flush()

        adressier_session.add_all(
            [
                EquipeDB(nom="VOLLEY TEST M", club_id=club.id),
                EquipeDB(nom="VOLLEY TEST F", club_id=club.id),
            ]
        )
        adressier_session.flush()

        service = ExportImportService(adressier_session)
        clubs_info = [
            AdressierClubInfo(
                code_ffvb="0123000",
                nom="ASSOCIATION SPORTIVE VOLLEY TEST",
            )
        ]

        service.enrich_clubs(
            clubs_info,
            "ABCCS",
            "2025/2026",
            "https://www.ffvbbeach.org/ffvbapp/resu/",
        )

        loaded = adressier_session.execute(
            select(ClubDB).where(ClubDB.code_ffvb == "0123000")
        ).scalar_one()
        assert loaded.nom_court == "VOLLEY TEST"

    def test_enrich_updates_salles(self, adressier_session):
        """Remplace les salles existantes lors de la mise à jour."""
        # Créer un club avec une salle
        club = ClubDB(nom="CLUB X", code_ffvb="0111111")
        adressier_session.add(club)
        adressier_session.flush()
        salle = SalleClubDB(
            club_id=club.id, numero=1, nom="ANCIENNE SALLE", capacite=100,
        )
        adressier_session.add(salle)
        adressier_session.flush()

        # Enrichir avec de nouvelles données
        service = ExportImportService(adressier_session)
        clubs_info = [
            AdressierClubInfo(
                code_ffvb="0111111",
                nom="CLUB X UPDATED",
                salles=[
                    SalleInfo(numero=1, nom="NOUVELLE SALLE", capacite=500),
                ],
            )
        ]

        service.enrich_clubs(
            clubs_info, "ABCCS", "2025/2026",
            "https://www.ffvbbeach.org/ffvbapp/resu/",
            force_reenrich=True,
        )

        salles = adressier_session.execute(
            select(SalleClubDB).where(SalleClubDB.club_id == club.id)
        ).scalars().all()
        assert len(salles) == 1
        assert salles[0].nom == "NOUVELLE SALLE"
        assert salles[0].capacite == 500

    def test_enrich_skips_without_code(self, adressier_session):
        """Ignore les clubs sans code FFVB."""
        service = ExportImportService(adressier_session)
        clubs_info = [
            AdressierClubInfo(code_ffvb="", nom="CLUB SANS CODE"),
        ]

        stats = service.enrich_clubs(
            clubs_info, "ABCCS", "2025/2026",
            "https://www.ffvbbeach.org/ffvbapp/resu/",
        )

        assert stats["skipped"] == 1
        assert stats["enriched"] == 0

    def test_enrich_skips_already_enriched_by_default(self, adressier_session):
        """N'écrase pas un club déjà enrichi sans demande explicite."""
        club = ClubDB(
            nom="CLUB STABLE",
            code_ffvb="0777000",
            correspondant_email="ancien@club.fr",
        )
        adressier_session.add(club)
        adressier_session.flush()

        service = ExportImportService(adressier_session)
        clubs_info = [
            AdressierClubInfo(
                code_ffvb="0777000",
                nom="CLUB STABLE UPDATED",
                correspondant_email="nouveau@club.fr",
                couleurs="ROUGE",
            )
        ]

        stats = service.enrich_clubs(
            clubs_info,
            "ABCCS",
            "2025/2026",
            "https://www.ffvbbeach.org/ffvbapp/resu/",
        )

        assert stats["created"] == 0
        assert stats["enriched"] == 0
        assert stats["skipped"] == 1

        loaded = adressier_session.execute(
            select(ClubDB).where(ClubDB.code_ffvb == "0777000")
        ).scalar_one()
        assert loaded.correspondant_email == "ancien@club.fr"
        assert loaded.couleurs is None

    def test_enrich_can_force_reenrich_existing_club(self, adressier_session):
        """Ré-enrichit un club déjà enrichi quand le mode forcé est activé."""
        club = ClubDB(
            nom="CLUB FORCE",
            code_ffvb="0777001",
            correspondant_email="ancien@club.fr",
        )
        adressier_session.add(club)
        adressier_session.flush()

        service = ExportImportService(adressier_session)
        clubs_info = [
            AdressierClubInfo(
                code_ffvb="0777001",
                nom="CLUB FORCE UPDATED",
                correspondant_email="nouveau@club.fr",
                couleurs="BLEU",
            )
        ]

        stats = service.enrich_clubs(
            clubs_info,
            "ABCCS",
            "2025/2026",
            "https://www.ffvbbeach.org/ffvbapp/resu/",
            force_reenrich=True,
        )

        assert stats["created"] == 0
        assert stats["enriched"] == 1
        assert stats["skipped"] == 0

        loaded = adressier_session.execute(
            select(ClubDB).where(ClubDB.code_ffvb == "0777001")
        ).scalar_one()
        assert loaded.correspondant_email == "nouveau@club.fr"
        assert loaded.couleurs == "BLEU"

    def test_enrich_multiple_clubs(self, adressier_session):
        """Enrichit plusieurs clubs d'un coup."""
        # Créer un club existant
        club1 = ClubDB(nom="CLUB A", code_ffvb="0000001")
        adressier_session.add(club1)
        adressier_session.flush()

        service = ExportImportService(adressier_session)
        clubs_info = [
            AdressierClubInfo(
                code_ffvb="0000001", nom="CLUB A UPDATED",
                ligue="Ligue X", couleurs="ROUGE",
            ),
            AdressierClubInfo(
                code_ffvb="0000002", nom="CLUB B NEW",
                ligue="Ligue Y", couleurs="BLEU",
            ),
        ]

        stats = service.enrich_clubs(
            clubs_info, "ABCCS", "2025/2026",
            "https://www.ffvbbeach.org/ffvbapp/resu/",
        )

        assert stats["enriched"] == 1
        assert stats["created"] == 1

        # Vérifier les deux clubs
        all_clubs = adressier_session.execute(select(ClubDB)).scalars().all()
        assert len(all_clubs) == 2


# =====================================================================
# Tests du modèle ClubDB enrichi
# =====================================================================

class TestClubDBModel:
    """Tests du modèle ClubDB avec les champs adressier."""

    def test_new_club_fields(self, adressier_session):
        """Vérifie que les nouveaux champs sont bien persistés."""
        club = ClubDB(
            nom="TEST CLUB",
            code_ffvb="0123456",
            ligue="Ligue TEST",
            couleurs="BLANC ET NOIR",
            president="M. TEST",
            entraineur="M. COACH",
            entraineur_adjoint="M. ADJOINT",
            correspondant_nom="M. CONTACT",
            correspondant_adresse="1 RUE TEST",
            correspondant_ville="75000 PARIS",
            correspondant_telephone="01.02.03.04.05",
            correspondant_portable="06.01.02.03.04",
            correspondant_email="test@test.fr",
        )
        adressier_session.add(club)
        adressier_session.flush()

        loaded = adressier_session.execute(
            select(ClubDB).where(ClubDB.id == club.id)
        ).scalar_one()

        assert loaded.ligue == "Ligue TEST"
        assert loaded.couleurs == "BLANC ET NOIR"
        assert loaded.president == "M. TEST"
        assert loaded.correspondant_email == "test@test.fr"

    def test_salle_club_relationship(self, adressier_session):
        """Vérifie la relation ClubDB ← SalleClubDB."""
        club = ClubDB(nom="CLUB SALLE", code_ffvb="0111222")
        adressier_session.add(club)
        adressier_session.flush()

        s1 = SalleClubDB(
            club_id=club.id, numero=1,
            nom="GYMNASE A", sol="parquet", capacite=1000,
        )
        s2 = SalleClubDB(
            club_id=club.id, numero=2,
            nom="GYMNASE B", sol="taraflex", capacite=500,
        )
        adressier_session.add_all([s1, s2])
        adressier_session.flush()

        loaded = adressier_session.execute(
            select(ClubDB).where(ClubDB.id == club.id)
        ).scalar_one()

        assert len(loaded.salles) == 2
        noms = {s.nom for s in loaded.salles}
        assert "GYMNASE A" in noms
        assert "GYMNASE B" in noms

    def test_salle_unique_constraint(self, adressier_session):
        """Vérifie la contrainte d'unicité (club_id, numero)."""
        club = ClubDB(nom="CLUB UC", code_ffvb="0333444")
        adressier_session.add(club)
        adressier_session.flush()

        s1 = SalleClubDB(club_id=club.id, numero=1, nom="SALLE 1")
        adressier_session.add(s1)
        adressier_session.flush()

        s1_dup = SalleClubDB(club_id=club.id, numero=1, nom="SALLE 1 DUP")
        adressier_session.add(s1_dup)

        with pytest.raises(Exception):  # IntegrityError
            adressier_session.flush()
        adressier_session.rollback()


# =====================================================================
# Tests d'import de matchs avec source_url (feuille de match)
# =====================================================================

class TestImportMatchWithSourceUrl:
    """Vérifie que la feuille de match est bien stockée comme source_url."""

    def test_feuille_match_url_stored(self, adressier_session):
        """L'URL de la feuille de match est stockée dans source_url."""
        from pyvolley.scrapers.ffvb.export_scraper import ExportMatchInfo
        from pyvolley.database.models import MatchDB

        service = ExportImportService(adressier_session)
        matches = [
            ExportMatchInfo(
                code_match="EMA001",
                entite_code="ABCCS",
                poule_code="EMA",
                saison="2025/2026",
                journee="01",
                equipe_a_nom="GRENOBLE VUC",
                equipe_b_nom="HARNES VB",
                club_a_code_ffvb="0382201",
                club_b_code_ffvb="0622126",
                match_joue=True,
                score_sets="3/1",
                vainqueur="GRENOBLE VUC",
                feuille_match_url="https://www.ffvbbeach.org/ffvbapp/resu/ffvolley_fdme.php?saison=2025%2F2026&codent=ABCCS&codmatch=EMA001",
            )
        ]

        stats = service.import_matches(matches, "ABCCS", "2025/2026")
        adressier_session.flush()

        assert stats["imported"] == 1

        match = adressier_session.execute(
            select(MatchDB).where(MatchDB.code_match == "EMA001")
        ).scalar_one()

        assert match.source_url is not None
        assert "ffvolley_fdme.php" in match.source_url
        assert "codmatch=EMA001" in match.source_url
        assert match.parsing_status == "discovered"
        assert match.score_source == "export"

    def test_source_url_change_requeues_already_parsed_match(self, adressier_session):
        """Un changement d'URL source remet proprement le match dans la file parse."""
        from datetime import datetime

        from pyvolley.scrapers.ffvb.export_scraper import ExportMatchInfo
        from pyvolley.database.models import MatchDB

        service = ExportImportService(adressier_session)
        initial_url = (
            "https://www.ffvbbeach.org/ffvbapp/resu/ffvolley_fdme.php?"
            "saison=2025%2F2026&codent=ABCCS&codmatch=EMA010"
        )
        updated_url = f"{initial_url}&rev=2"

        first_batch = [
            ExportMatchInfo(
                code_match="EMA010",
                entite_code="ABCCS",
                poule_code="EMA",
                saison="2025/2026",
                equipe_a_nom="GRENOBLE VUC",
                equipe_b_nom="HARNES VB",
                club_a_code_ffvb="0382201",
                club_b_code_ffvb="0622126",
                match_joue=True,
                score_sets="3/1",
                vainqueur="GRENOBLE VUC",
                feuille_match_url=initial_url,
            )
        ]

        stats_first = service.import_matches(first_batch, "ABCCS", "2025/2026")
        assert stats_first["imported"] == 1

        match = adressier_session.execute(
            select(MatchDB).where(MatchDB.code_match == "EMA010")
        ).scalar_one()
        match.parsing_status = "parsed"
        match.has_details = True
        match.source_pdf = "data/pdfs/2025-2026/ABCCS/EMA/EMA010.pdf"
        match.parsed_at = datetime(2026, 1, 3, 10, 30, 0)
        adressier_session.flush()

        second_batch = [
            ExportMatchInfo(
                code_match="EMA010",
                entite_code="ABCCS",
                poule_code="EMA",
                saison="2025/2026",
                equipe_a_nom="GRENOBLE VUC",
                equipe_b_nom="HARNES VB",
                club_a_code_ffvb="0382201",
                club_b_code_ffvb="0622126",
                match_joue=True,
                score_sets="3/1",
                vainqueur="GRENOBLE VUC",
                feuille_match_url=updated_url,
            )
        ]

        stats_second = service.import_matches(second_batch, "ABCCS", "2025/2026")
        assert stats_second["updated"] == 1

        refreshed = adressier_session.execute(
            select(MatchDB).where(MatchDB.code_match == "EMA010")
        ).scalar_one()
        assert refreshed.source_url == updated_url
        assert refreshed.parsing_status == "discovered"
        assert refreshed.source_pdf is None
        assert refreshed.parsed_at is None

    def test_import_creates_clubs_and_equipes(self, adressier_session):
        """L'import crée automatiquement les clubs et équipes."""
        from pyvolley.scrapers.ffvb.export_scraper import ExportMatchInfo
        from pyvolley.database.models import EquipeDB

        service = ExportImportService(adressier_session)
        matches = [
            ExportMatchInfo(
                code_match="2FA001",
                entite_code="ABCCS",
                poule_code="2FA",
                saison="2025/2026",
                equipe_a_nom="VITROLLES SPORTS VB",
                equipe_b_nom="MARSEILLE VB",
                club_a_code_ffvb="0136082",
                club_b_code_ffvb="0134567",
                feuille_match_url="https://example.com/match",
            )
        ]

        service.import_matches(matches, "ABCCS", "2025/2026")
        adressier_session.flush()

        # Vérifier les clubs
        club_a = adressier_session.execute(
            select(ClubDB).where(ClubDB.code_ffvb == "0136082")
        ).scalar_one()
        assert club_a.nom == "VITROLLES SPORTS VB"

        club_b = adressier_session.execute(
            select(ClubDB).where(ClubDB.code_ffvb == "0134567")
        ).scalar_one()
        assert club_b.nom == "MARSEILLE VB"

        # Vérifier les équipes
        equipes = adressier_session.execute(select(EquipeDB)).scalars().all()
        assert len(equipes) == 2

    def test_export_import_persists_detailed_sets(self, adressier_session):
        """Les scores détaillés de sets sont stockés dès l'import export."""
        from pyvolley.scrapers.ffvb.export_scraper import ExportMatchInfo
        from pyvolley.database.models import MatchDB

        service = ExportImportService(adressier_session)
        matches = [
            ExportMatchInfo(
                code_match="EMA777",
                entite_code="ABCCS",
                poule_code="EMA",
                saison="2025/2026",
                equipe_a_nom="GRENOBLE VUC",
                equipe_b_nom="HARNES VB",
                club_a_code_ffvb="0382201",
                club_b_code_ffvb="0622126",
                match_joue=True,
                score_sets="3/1",
                sets=[(25, 20), (23, 25), (25, 19), (25, 18)],
                vainqueur="GRENOBLE VUC",
            )
        ]

        stats = service.import_matches(matches, "ABCCS", "2025/2026")
        adressier_session.flush()

        assert stats["imported"] == 1

        match = adressier_session.execute(
            select(MatchDB).where(MatchDB.code_match == "EMA777")
        ).scalar_one()
        assert match.has_details is True
        assert match.score_source == "export"

        sets = adressier_session.execute(
            select(SetDB).where(SetDB.match_id == match.id).order_by(SetDB.numero)
        ).scalars().all()
        assert len(sets) == 4
        assert (sets[0].score_a, sets[0].score_b) == (25, 20)
        assert (sets[3].score_a, sets[3].score_b) == (25, 18)
