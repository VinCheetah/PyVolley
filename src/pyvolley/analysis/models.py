"""
Modèles de résultats d'analyse.

Ces modèles définissent le format de sortie standardisé
pour toutes les analyses (match, joueur, équipe, compétition).
"""

from datetime import date as datetime_date, time as datetime_time
from typing import Optional
from pydantic import BaseModel, Field


# ============== Résultats joueur =============

class ServiceStats(BaseModel):
    """Statistiques de service pour un joueur sur un set ou un match."""
    nb_tours: int = 0
    points_marques: int = Field(
        0,
        description=(
            "Nombre total de points marqués pendant les tours au service. "
            "Calculé comme la somme des points gagnés entre le début de chaque "
            "tour de service et le score au moment de la perte du service."
        ),
    )
    detail_par_set: dict[int, list[int]] = Field(
        default_factory=dict,
        description="Par numéro de set : liste des scores à la perte de service",
    )


class PresenceSet(BaseModel):
    """Présence d'un joueur sur un set."""
    set_numero: int
    titulaire: bool = False
    entre_en_jeu: bool = False
    sorti: bool = False
    position_depart: Optional[int] = None
    score_entree: Optional[str] = None
    score_sortie: Optional[str] = None


class JoueurMatchAnalysis(BaseModel):
    """Analyse complète d'un joueur lors d'un match."""
    # Identité
    numero: str
    nom: str
    prenom: str
    licence: str
    equipe: str
    est_libero: bool = False
    est_capitaine: bool = False

    # Présence
    sets_joues: int = 0
    sets_titulaire: int = 0
    presence_par_set: list[PresenceSet] = Field(default_factory=list)

    # Services
    services: ServiceStats = Field(default_factory=ServiceStats)

    # Temps de jeu estimé (en minutes)
    temps_jeu_estime: Optional[float] = None

    # Changements
    nb_entrees: int = 0
    nb_sorties: int = 0

    # Sanctions
    sanctions: list[str] = Field(
        default_factory=list, description="Ex: ['A (set 2, 15-12)']"
    )


# ============== Statistiques détaillées joueur par match ==============

class ServiceSetDetail(BaseModel):
    """Détail de service pour un set."""
    set_numero: int
    nb_services: int = 0
    nb_series: int = 0
    max_serie: int = 0
    nb_tours: int = 0
    points_marques: int = 0
    meilleure_serie: int = 0
    scores_perte: list[int] = Field(default_factory=list)


class JoueurMatchDetailedStats(BaseModel):
    """Statistiques détaillées d'un joueur pour un match.

    Inclut points gagnés/perdus, services, meilleure série,
    temps de jeu estimé, changements, temps morts provoqués, etc.
    """
    # Identité
    numero: str
    nom: str
    prenom: str
    licence: str
    equipe: str
    side: str  # "A" ou "B"
    est_libero: bool = False
    est_capitaine: bool = False

    # Résultat du match
    victoire: bool = False
    score_match: Optional[str] = None  # "3-1"

    # Points
    points_gagnes: int = Field(0, description="Points gagnés par l'équipe pendant la présence du joueur")
    points_gagnes_service: int = Field(0, description="Points marqués au service par le joueur")
    points_perdus: int = Field(0, description="Points estimés perdus (points adverses pendant présence)")
    points_joues: int = Field(0, description="Nombre total de points joués pendant la présence")
    ratio_points_gagnes: float = Field(0.0, description="Part des points gagnés pendant la présence")

    # Services
    services: int = Field(0, description="Nombre total de services effectués")
    serie: int = Field(0, description="Nombre de séries de service")
    max_serie: int = Field(0, description="Longueur maximale d'une série de service")
    moyenne_services_par_serie: float = Field(0.0, description="Nombre moyen de services par série")
    nb_services: int = Field(0, description="Nombre total de tours de service")
    meilleure_serie: int = Field(0, description="Plus longue série de services consécutifs (points au service)")
    detail_services_par_set: list[ServiceSetDetail] = Field(default_factory=list)

    # Présence
    sets_joues: int = 0
    sets_titulaire: int = 0
    presence_par_set: list[PresenceSet] = Field(default_factory=list)

    # Temps de jeu
    temps_jeu_estime: Optional[float] = Field(None, description="Temps de jeu estimé en minutes")
    temps_jeu_par_set: dict[int, float] = Field(default_factory=dict, description="Temps par set en minutes")

    # Changements
    nb_entrees: int = 0
    nb_sorties: int = 0
    nb_changements_total: int = Field(0, description="Total entrées + sorties")

    # Temps morts provoqués (pris par l'adversaire pendant une série de service)
    temps_morts_provoques: int = Field(
        0,
        description="Nombre de temps morts pris par l'adversaire pendant une série de service du joueur",
    )

    # Sanctions
    sanctions: list[str] = Field(default_factory=list)

    # Mode libéro
    est_calcul_libero: bool = Field(False, description="Stats calculées en mode libéro")
    joueurs_remplaces: list[str] = Field(
        default_factory=list,
        description="Numéros des joueurs remplacés par le libéro",
    )

    # Mode remplacement libéro
    remplace_par_libero: bool = Field(False, description="Joueur remplacé par un libéro en zone arrière")


class JoueurStatsAggregated(BaseModel):
    """Statistiques agrégées d'un joueur sur plusieurs matchs."""
    nom: str
    prenom: str
    licence: str

    # Nombre de matchs
    matchs_joues: int = 0
    matchs_victoires: int = 0
    matchs_defaites: int = 0

    # Sets
    total_sets_joues: int = 0
    total_sets_titulaire: int = 0

    # Points
    total_points_gagnes: int = 0
    total_points_gagnes_service: int = 0
    total_points_perdus: int = 0
    total_points_joues: int = 0
    ratio_points_gagnes_global: float = 0.0

    # Services
    total_services: int = 0
    total_series_service: int = 0
    max_serie_service: int = 0
    moyenne_services_par_serie: float = 0.0
    total_tours_service: int = 0
    meilleure_serie_service: int = 0
    moyenne_points_par_tour: float = 0.0

    # Temps de jeu
    total_temps_jeu: float = 0.0
    moyenne_temps_par_match: float = 0.0

    # Changements
    total_entrees: int = 0
    total_sorties: int = 0

    # Temps morts provoqués
    total_temps_morts_provoques: int = 0
    moyenne_temps_morts_par_match: float = 0.0

    # Sanctions
    total_sanctions: int = 0


# ============== Résultats set ==============

class SetAnalysis(BaseModel):
    """Analyse d'un set."""
    numero: int
    score: str = ""
    duree_minutes: Optional[int] = None
    vainqueur: Optional[str] = None
    service_initial: Optional[str] = None

    # Formations
    formation_a: Optional[list[Optional[str]]] = None
    formation_b: Optional[list[Optional[str]]] = None

    # Résumé changements
    nb_changements_a: int = 0
    nb_changements_b: int = 0

    # Résumé timeouts
    nb_timeouts_a: int = 0
    nb_timeouts_b: int = 0

    # Résumé services
    nb_tours_service_a: int = 0
    nb_tours_service_b: int = 0


# ============== Résultat match ==============

class MatchAnalysis(BaseModel):
    """Analyse complète d'un match."""
    # Identifiant
    code_match: str
    date: Optional[datetime_date] = None
    lieu: Optional[str] = None
    competition: Optional[str] = None

    # Résultat global
    equipe_a: str
    equipe_b: str
    vainqueur: Optional[str] = None
    score_sets: Optional[str] = None
    sets_a: int = 0
    sets_b: int = 0
    duree_totale: Optional[str] = None

    # Analyse par set
    sets: list[SetAnalysis] = Field(default_factory=list)

    # Analyse joueurs
    joueurs_a: list[JoueurMatchAnalysis] = Field(default_factory=list)
    joueurs_b: list[JoueurMatchAnalysis] = Field(default_factory=list)

    # Statistiques globales
    total_changements_a: int = 0
    total_changements_b: int = 0
    total_timeouts_a: int = 0
    total_timeouts_b: int = 0
    total_sanctions: int = 0


# ============== Résultats équipe / club ==============

class EquipeSeasonRecord(BaseModel):
    """Bilan d'une équipe sur une période."""
    equipe: str
    saison: Optional[str] = None
    competition: Optional[str] = None

    matchs_joues: int = 0
    victoires: int = 0
    defaites: int = 0
    ratio_victoires: float = 0.0

    sets_gagnes: int = 0
    sets_perdus: int = 0
    ratio_sets: float = 0.0

    points_marques: int = 0
    points_encaisses: int = 0
    ratio_points: float = 0.0

    # Meilleures/pires performances
    plus_large_victoire: Optional[str] = None
    plus_large_defaite: Optional[str] = None

    # Joueurs
    joueurs_utilises: int = 0
    joueur_plus_present: Optional[str] = None


class JoueurSeasonRecord(BaseModel):
    """Bilan d'un joueur sur une saison."""
    nom: str
    prenom: str
    licence: str
    equipe: str

    matchs_joues: int = 0
    sets_joues: int = 0
    sets_titulaire: int = 0
    temps_jeu_estime: float = 0.0

    # Services agrégés
    total_tours_service: int = 0
    total_points_service: int = 0
    moyenne_points_par_tour: float = 0.0


# ============== Résultats compétition ==============

class CompetitionAnalysis(BaseModel):
    """Analyse d'une compétition."""
    nom: str
    saison: Optional[str] = None
    ligue: Optional[str] = None

    nb_matchs: int = 0
    nb_equipes: int = 0
    nb_joueurs: int = 0

    classement: list[EquipeSeasonRecord] = Field(default_factory=list)
    meilleurs_serveurs: list[JoueurSeasonRecord] = Field(default_factory=list)
