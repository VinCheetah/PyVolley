"""
Tests pour le helper d'évolution des équipes et la section web sur la page club.
"""

from unittest.mock import MagicMock
import pytest
from starlette.testclient import TestClient

from pyvolley.web.helpers.club_evolution import (
    build_club_evolution_data,
    _extract_team_number,
    _is_coupe_de_france,
    _format_youth_label,
)
from pyvolley.web.app import create_web_app


def _make_mock_equipe(
    id: int,
    nom: str,
    saison_code: str,
    genre: str | None = "MASCULIN",
    categorie: str | None = "SENIOR",
    niveau: str | None = "REGIONALE",
    division: str | None = None,
    comp_nom: str | None = "Régionale 1",
    entite_code: str | None = None,
    entite_nom: str | None = None,
):
    eq = MagicMock()
    eq.id = id
    eq.nom = nom
    eq.genre = genre
    eq.categorie = categorie
    eq.niveau = niveau
    eq.division = division
    eq.saison = MagicMock(code=saison_code)
    entite_mock = MagicMock(code=entite_code, nom=entite_nom) if entite_code or entite_nom else None
    eq.competition = MagicMock(
        nom=comp_nom,
        code_competition=comp_nom,
        genre=genre,
        categorie=categorie,
        niveau=niveau,
        division=division,
        entite=entite_mock,
    )
    return eq


def test_empty_equipes():
    data = build_club_evolution_data([])
    assert data["has_data"] is False
    assert data["charts"] == {}
    assert data["transitions"] == []


def test_extract_team_number():
    assert _extract_team_number("BESANCON VOLLEY-BALL") == 1
    assert _extract_team_number("BESANCON VOLLEY-BALL 1") == 1
    assert _extract_team_number("BESANCON VOLLEY-BALL - 2") == 2
    assert _extract_team_number("ESM 3") == 3
    assert _extract_team_number("DTVB 4") == 4


def test_is_coupe_de_france():
    assert _is_coupe_de_france("COUPE DE FRANCE M18", "COUPE_DE_FRANCE") is True
    assert _is_coupe_de_france("CdF Féminine", "COUPE_DE_FRANCE") is True
    assert _is_coupe_de_france("CHAMPIONNAT M15 FEMININ", "REGIONALE") is False
    assert _is_coupe_de_france("RÉGIONALE MASCULINE", "REGIONALE") is False


def test_format_youth_label():
    label_cdf, is_cdf = _format_youth_label("M18", "CdF Jeunes M18 Masc.", "Jeunes CdF")
    assert is_cdf is True
    assert label_cdf == "CdF M18"

    label_reg, is_cdf_reg = _format_youth_label("M15", "CHAMPIONNAT M15 FEMININ", "Régional")
    assert is_cdf_reg is False
    assert label_reg == "Régional M15"


def test_promotions_and_relegations_detection():
    equipes = [
        # Équipe 1 Masculine : Maintien en N2
        _make_mock_equipe(1, "TEST VB", "2023-2024", genre="MASCULIN", comp_nom="NATIONALE 2 MASCULINE", niveau="NATIONALE"),
        _make_mock_equipe(2, "TEST VB", "2024-2025", genre="MASCULIN", comp_nom="NATIONALE 2 MASCULINE", niveau="NATIONALE"),
        # Équipe 2 Masculine : Montée de Régional vers Prénat
        _make_mock_equipe(3, "TEST VB 2", "2023-2024", genre="MASCULIN", comp_nom="RÉGIONALE MASCULINE", niveau="REGIONALE"),
        _make_mock_equipe(4, "TEST VB 2", "2024-2025", genre="MASCULIN", comp_nom="PRENATIONALE MASCULINE", niveau="PRE_NATIONALE"),
        # Équipe 1 Féminine : Montée de Prénat vers N3
        _make_mock_equipe(5, "TEST VB 1", "2023-2024", genre="FEMININ", comp_nom="PRENATIONALE FEMININE", niveau="PRE_NATIONALE"),
        _make_mock_equipe(6, "TEST VB 1", "2024-2025", genre="FEMININ", comp_nom="NATIONALE 3 FÉMININE", niveau="NATIONALE"),
        # Jeunes Garçons M18 : Coupe de France
        _make_mock_equipe(7, "TEST VB", "2024-2025", genre="MASCULIN", categorie="M18", comp_nom="CdF Jeunes M18 Masc.", niveau="COUPE_DE_FRANCE"),
    ]

    # Ajout d'une équipe jeune en championnat régulier (doit aller dans main)
    equipes.append(
        _make_mock_equipe(8, "TEST VB", "2024-2025", genre="FEMININ", categorie="M18", comp_nom="CHAMPIONNAT M18 FEMININ", niveau="REGIONALE")
    )

    data = build_club_evolution_data(equipes)

    assert data["has_data"] is True
    charts = data["charts"]

    # Doit contenir le graphique principal 'main' et la coupe de France 'cdf'
    assert "main" in charts
    assert "cdf" in charts

    # Le graphique principal rassemble Hommes et Femmes et jeunes réguliers
    main_chart = charts["main"]
    ds_labels = [ds["label"] for ds in main_chart["datasets"]]
    assert any("Hommes" in lbl for lbl in ds_labels)
    assert any("Femmes" in lbl for lbl in ds_labels)
    assert any("M18" in lbl for lbl in ds_labels)

    # Règle stricte : Une seule couleur pour les hommes, une seule couleur pour les femmes
    hommes_colors = [ds["color"] for ds in main_chart["datasets"] if "Hommes" in ds["label"]]
    femmes_colors = [ds["color"] for ds in main_chart["datasets"] if "Femmes" in ds["label"]]
    assert len(set(hommes_colors)) == 1
    assert len(set(femmes_colors)) == 1
    for hc in hommes_colors:
        assert hc not in femmes_colors

    # Toutes les équipes visuellement identiques : ligne continue, ronds, team_ids cliquables
    eq1_h = next(ds for ds in main_chart["datasets"] if "Équipe 1" in ds["label"] and "Hommes" in ds["label"])
    eq2_h = next(ds for ds in main_chart["datasets"] if "Équipe 2" in ds["label"] and "Hommes" in ds["label"])
    assert eq1_h["border_dash"] == []
    assert eq2_h["border_dash"] == []
    assert eq1_h["point_style"] == "circle"
    assert eq2_h["point_style"] == "circle"
    assert eq1_h["point_radius"] == 8.0
    assert "team_ids" in eq1_h
    assert len(eq1_h["team_ids"]) == len(main_chart["seasons"])

    # Traits de séparation entre catégories et couloirs
    assert len(main_chart["separators"]) > 0
    assert len(main_chart["lanes"]) > 0

    # Le graphique CdF n'a que la Coupe de France
    cdf_chart = charts["cdf"]
    cdf_labels = [ds["label"] for ds in cdf_chart["datasets"]]
    assert len(cdf_labels) == 1
    assert "M18" in cdf_labels[0]
    # L'axe Y de CdF contient des catégories d'âge et des séparateurs
    cdf_tick_names = [t[1] for t in cdf_chart["y_ticks"]]
    assert "M18" in cdf_tick_names
    assert "separators" in cdf_chart
    assert "lanes" in cdf_chart

    # Vérification de l'adaptation de l'axe Y :
    # Le niveau max en championnat est N2 (12). Les divisions supérieures (N1, Élite, Pro B, Pro A) ne doivent PAS être affichées.
    main_tick_names = [t[1] for t in main_chart["y_ticks"]]
    assert "N2" in main_tick_names
    assert "N1" not in main_tick_names
    assert "Élite" not in main_tick_names
    assert "Pro A" not in main_tick_names
    assert main_chart["y_max"] <= 13.0

    # Vérification des transitions
    transitions = data["transitions"]
    promotions = [tr for tr in transitions if tr["status"] == "promotion"]
    assert len(promotions) >= 2

    # Montée Équipe 2 Hommes (Régional -> Prénat)
    promo_h = next(p for p in promotions if "Équipe 2" in p["team_name"] and p["genre_tag"] == "Hommes")
    assert promo_h["level_from"] == "Régional"
    assert promo_h["level_to"] == "Prénat"

    # Montée Équipe 1 Femmes (Prénat -> N3)
    promo_f = next(p for p in promotions if "Équipe 1" in p["team_name"] and p["genre_tag"] == "Femmes")
    assert promo_f["level_from"] == "Prénat"
    assert promo_f["level_to"] == "N3"

    # Maintien Équipe 1 Hommes en N2
    maintiens = [tr for tr in transitions if tr["status"] == "stable"]
    maintien_h = next(m for m in maintiens if "Équipe 1" in m["team_name"] and m["genre_tag"] == "Hommes")
    assert maintien_h["level_from"] == "N2"
    assert maintien_h["level_to"] == "N2"


def test_anti_superposition_jitter():
    """Vérifie que deux équipes au même niveau dans la même saison ne se superposent pas sur le graphique."""
    equipes = [
        # Équipe 1 Hommes en Prénat en 2024-2025
        _make_mock_equipe(1, "CLUB TEST 1", "2024-2025", genre="MASCULIN", comp_nom="PRENATIONALE MASCULINE", niveau="PRE_NATIONALE"),
        # Équipe 1 Femmes en Prénat en 2024-2025 (même niveau !)
        _make_mock_equipe(2, "CLUB TEST 1", "2024-2025", genre="FEMININ", comp_nom="PRENATIONALE FEMININE", niveau="PRE_NATIONALE"),
        # Équipe 2 Hommes aussi en Prénat en 2024-2025 (3 équipes au même niveau !)
        _make_mock_equipe(3, "CLUB TEST 2", "2024-2025", genre="MASCULIN", comp_nom="PRENATIONALE MASCULINE", niveau="PRE_NATIONALE"),
    ]

    data = build_club_evolution_data(equipes)
    chart = data["charts"]["main"]
    datasets = chart["datasets"]

    # Chaque dataset a une valeur pour la saison 2024-2025
    saison_idx = chart["seasons"].index("2024-2025")
    valeurs_y = [ds["data"][saison_idx] for ds in datasets]

    # Toutes les valeurs Y doivent être légèrement différentes (pas de superposition)
    assert len(set(valeurs_y)) == len(valeurs_y) == 3

    # Mais les labels de niveau doivent tous indiquer fidèlement 'Prénat'
    for ds in datasets:
        assert ds["level_labels"][saison_idx] == "Prénat"


@pytest.fixture
def client_with_db():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool
    from pyvolley.database.models import (
        Base,
        EquipeDB,
        ClubDB,
        CompetitionDB,
        SaisonDB,
    )
    from pyvolley.api.dependencies import get_session

    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    TestingSessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    session = TestingSessionLocal()

    saison1 = SaisonDB(code="2023-2024", nom="Saison 2023-2024")
    saison2 = SaisonDB(code="2024-2025", nom="Saison 2024-2025")
    club = ClubDB(nom="Volley Club Test")
    session.add_all([saison1, saison2, club])
    session.flush()

    comp_reg = CompetitionDB(nom="Régionale Masculine", niveau="REGIONALE", genre="MASCULIN", categorie="SENIOR", saison_id=saison1.id)
    comp_prenat = CompetitionDB(nom="Prénationale Masculine", niveau="PRE_NATIONALE", genre="MASCULIN", categorie="SENIOR", saison_id=saison2.id)
    session.add_all([comp_reg, comp_prenat])
    session.flush()

    eq1 = EquipeDB(nom="Volley Club Test 1", club_id=club.id, competition_id=comp_reg.id, saison_id=saison1.id, genre="MASCULIN", categorie="SENIOR", niveau="REGIONALE")
    eq2 = EquipeDB(nom="Volley Club Test 1", club_id=club.id, competition_id=comp_prenat.id, saison_id=saison2.id, genre="MASCULIN", categorie="SENIOR", niveau="PRE_NATIONALE")
    session.add_all([eq1, eq2])
    session.commit()

    app = create_web_app()
    app.dependency_overrides[get_session] = lambda: session

    with TestClient(app) as client:
        yield client

    Base.metadata.drop_all(engine)


def test_club_page_renders_with_evolution(client_with_db):
    """Vérifie que la page de détail d'un club s'affiche avec la section d'évolution."""
    response = client_with_db.get("/clubs/1")
    assert response.status_code == 200
    html = response.text
    assert "Évolution des Niveaux" in html
    assert "evolution-charts-grid" in html
    assert "evolution-movements-section" in html
    assert "Montée / Accession" in html


def test_contextual_ladder_no_ghost_levels():
    """Vérifie qu'un club ayant seulement Dép, Régionale et Prénat n'affiche AUCUN échelon fantôme."""
    equipes = [
        _make_mock_equipe(1, "CLUB X 1", "2023-2024", genre="MASCULIN", comp_nom="DÉPARTEMENTALE MASCULINE", niveau="DEPARTEMENTALE"),
        _make_mock_equipe(2, "CLUB X 1", "2024-2025", genre="MASCULIN", comp_nom="RÉGIONALE MASCULINE", niveau="REGIONALE"),
        _make_mock_equipe(3, "CLUB X 2", "2024-2025", genre="MASCULIN", comp_nom="PRENATIONALE MASCULINE", niveau="PRE_NATIONALE"),
    ]

    data = build_club_evolution_data(equipes)
    chart = data["charts"]["main"]
    tick_labels = [lbl for _, lbl in chart["y_ticks"]]

    # Exactement les 3 échelons du club
    assert tick_labels == ["Dép", "Régionale", "Prénat"]

    # Absolument aucun niveau fantôme
    for ghost in ["D4", "D3", "D2", "D1", "Préreg", "R4", "R3", "R2", "R1", "N3", "N2", "N1", "Élite", "Pro B", "Pro A"]:
        assert ghost not in tick_labels


def test_contextual_ladder_promotion_step_accuracy():
    """Vérifie que la montée entre deux échelons consécutifs du club indique exactement +1 niveau(x)."""
    equipes = [
        _make_mock_equipe(1, "CLUB X 1", "2023-2024", genre="MASCULIN", comp_nom="DÉPARTEMENTALE MASCULINE", niveau="DEPARTEMENTALE"),
        _make_mock_equipe(2, "CLUB X 1", "2024-2025", genre="MASCULIN", comp_nom="RÉGIONALE MASCULINE", niveau="REGIONALE"),
    ]

    data = build_club_evolution_data(equipes)
    transitions = data["transitions"]
    assert len(transitions) == 1
    tr = transitions[0]
    assert tr["status"] == "promotion"
    assert tr["delta_text"] == "+1 niveau(x)"


def test_contextual_ladder_departmental_reorganization_maintien():
    """Vérifie que le passage de Dép à D1 lors d'une réorganisation est un maintien et non une fausse montée."""
    equipes = [
        _make_mock_equipe(1, "CLUB X 1", "2023-2024", genre="MASCULIN", comp_nom="DÉPARTEMENTALE MASCULINE", niveau="DEPARTEMENTALE"),
        _make_mock_equipe(2, "CLUB X 1", "2024-2025", genre="MASCULIN", comp_nom="DÉPARTEMENTALE 1 MASCULINE", niveau="DEPARTEMENTALE", division="1"),
        _make_mock_equipe(3, "CLUB X 2", "2024-2025", genre="MASCULIN", comp_nom="DÉPARTEMENTALE 2 MASCULINE", niveau="DEPARTEMENTALE", division="2"),
    ]

    data = build_club_evolution_data(equipes)
    chart = data["charts"]["main"]
    tick_labels = [lbl for _, lbl in chart["y_ticks"]]

    # D1 et Dép sont unifiés au même échelon sportif
    assert "D1 / Dép" in tick_labels
    assert "D2" in tick_labels

    # La transition de l'Équipe 1 (Dép -> D1) doit être un MAINTIEN
    tr_eq1 = next(tr for tr in data["transitions"] if "Équipe 1" in tr["team_name"])
    assert tr_eq1["status"] == "stable"
    assert tr_eq1["delta_text"] == "Maintien"


def test_contextual_ladder_n1_to_elite_historical_rename():
    """Vérifie que le passage de N1 à Élite (ancienne dénomination) est un maintien."""
    equipes = [
        _make_mock_equipe(1, "CLUB X 1", "2023-2024", genre="MASCULIN", comp_nom="NATIONALE 1 MASCULINE", niveau="NATIONALE"),
        _make_mock_equipe(2, "CLUB X 1", "2024-2025", genre="MASCULIN", comp_nom="ELITE MASCULINE", niveau="ELITE"),
    ]

    data = build_club_evolution_data(equipes)
    chart = data["charts"]["main"]
    tick_labels = [lbl for _, lbl in chart["y_ticks"]]

    # N1 et Élite partagent le même palier
    assert any("Élite" in lbl and "N1" in lbl for lbl in tick_labels)

    # La transition est un maintien
    tr_eq1 = next(tr for tr in data["transitions"] if "Équipe 1" in tr["team_name"])
    assert tr_eq1["status"] == "stable"
    assert tr_eq1["delta_text"] == "Maintien"


def test_compet_lib_elite_is_loisir():
    """Un département n'a pas de niveau Élite : Compet'lib Élite doit être Loisir."""
    eq = _make_mock_equipe(1, "CLUB 1", "2024-2025", comp_nom="COMPET'LIB ELITE POULE A", niveau="ELITE")
    data = build_club_evolution_data([eq])
    chart = data["charts"]["main"]
    tick_labels = [lbl for _, lbl in chart["y_ticks"]]
    assert "Loisir" in tick_labels
    assert "Élite" not in tick_labels


def test_coupe_de_france_m11_and_volley_assis():
    """Coupe de France M11F et Volley Assis (CFA en ADPVA)."""
    eq_m11 = _make_mock_equipe(10, "CLUB M11", "2024-2025", comp_nom="COUPE DE FRANCE M11F 2X2 - ETAPE DEPARTEMENTALE", categorie="M11")
    eq_assis = _make_mock_equipe(11, "CLUB ASSIS", "2024-2025", comp_nom="CFA", entite_code="ADPVA", entite_nom="Compétitions Nationales PARA-VOLLEY Assis")

    data = build_club_evolution_data([eq_m11, eq_assis])
    assert "cdf" in data["charts"]
    cdf_chart = data["charts"]["cdf"]
    labels = [ds["label"] for ds in cdf_chart["datasets"]]
    assert any("M11" in l for l in labels)
    assert any("Volley Assis" in l for l in labels)


def test_no_ghost_r2_for_youth_regional_championship():
    """Vérifie qu'un championnat régional jeune avec poule 2 (ex: M15 2) ne crée pas de R2 sur l'axe."""
    equipes = [
        _make_mock_equipe(1, "CLUB 1", "2024-2025", comp_nom="PRENATIONALE MASCULINE", niveau="PRE_NATIONALE"),
        _make_mock_equipe(2, "CLUB M15", "2024-2025", comp_nom="CHAMPIONNAT REGIONAL M15 MASCULINS 2", categorie="M15", niveau="REGIONALE", division="2"),
        _make_mock_equipe(3, "CLUB M18", "2024-2025", comp_nom="CHAMPIONNAT REGIONAL ELITE M18", categorie="M18", niveau="REGIONALE"),
    ]
    data = build_club_evolution_data(equipes)
    chart = data["charts"]["main"]
    tick_labels = [lbl for _, lbl in chart["y_ticks"]]
    assert "R2" not in tick_labels
    assert "Prénat" in tick_labels
    assert any("Région" in l for l in tick_labels)
    assert any("Élite" in l for l in tick_labels)


