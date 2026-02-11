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
