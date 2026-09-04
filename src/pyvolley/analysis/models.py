"""Modèles Pydantic actifs pour la couche ``analysis``."""

from typing import Optional

from pydantic import BaseModel, Field


class PresenceSet(BaseModel):
    """Présence d'un joueur sur un set."""

    set_numero: int
    titulaire: bool = False
    entre_en_jeu: bool = False
    sorti: bool = False
    position_depart: Optional[int] = None
    score_entree: Optional[str] = None
    score_sortie: Optional[str] = None


class ServiceSetDetail(BaseModel):
    """Détail de service d'un joueur sur un set."""

    set_numero: int
    nb_services: int = 0
    nb_series: int = 0
    max_serie: int = 0
    nb_tours: int = 0
    points_marques: int = 0
    meilleure_serie: int = 0
    scores_perte: list[int] = Field(default_factory=list)


class RoleInference(BaseModel):
    """Role inference result for one player in one match context."""

    role_principal: Optional[str] = None
    roles_possibles: list[str] = Field(default_factory=list)
    role_scores: dict[str, float] = Field(default_factory=dict)
    role_confiance: float = 0.0
    indices: list[str] = Field(default_factory=list)
    role_atypique: bool = False
    composition_valid: bool = True
    evidence_breakdown: dict[str, float] = Field(default_factory=dict)


class JoueurMatchDetailedStats(BaseModel):
    """Statistiques détaillées d'un joueur pour un match."""

    numero: str
    nom: str
    prenom: str
    licence: str
    equipe: str
    side: str
    est_libero: bool = False
    est_capitaine: bool = False

    role_principal: Optional[str] = Field(
        None,
        description="Role principal infere sur ce match",
    )
    roles_possibles: list[str] = Field(
        default_factory=list,
        description="Roles potentiels classes par probabilite decroissante",
    )
    role_scores: dict[str, float] = Field(
        default_factory=dict,
        description="Scores normalises par role (somme ~= 1)",
    )
    role_confiance: float = Field(
        0.0,
        description="Confiance globale de l'inference de role",
    )
    indices_roles: list[str] = Field(
        default_factory=list,
        description="Indices textuels ayant contribue a l'inference",
    )
    role_atypique: bool = Field(
        False,
        description="Indique si le rôle inféré dévie du profil habituel du joueur",
    )

    victoire: bool = False
    score_match: Optional[str] = None

    points_gagnes: int = Field(
        0,
        description="Points gagnés par l'équipe pendant la présence du joueur",
    )
    points_gagnes_service: int = Field(
        0,
        description="Points marqués au service par le joueur",
    )
    points_perdus: int = Field(
        0,
        description="Points adverses encaissés pendant la présence",
    )
    points_joues: int = Field(
        0,
        description="Nombre total de points joués pendant la présence",
    )
    points_gagnes_sideout: int = Field(
        0,
        description="Points gagnés hors service (phases de side-out)",
    )
    ratio_points_gagnes: float = Field(
        0.0,
        description="Part des points gagnés pendant la présence",
    )
    break_point_ratio: float = Field(
        0.0,
        description="Ratio points de break / services effectués",
    )
    sideout_contribution_ratio: float = Field(
        0.0,
        description="Part des points gagnés hors service",
    )

    services: int = Field(0, description="Nombre total de services effectués")
    serie: int = Field(0, description="Nombre de tours/séries de service")
    max_serie: int = Field(0, description="Longueur maximale d'une série de service")
    moyenne_services_par_serie: float = Field(
        0.0,
        description="Nombre moyen de services par série",
    )
    nb_services: int = Field(
        0,
        description="Alias de services : nombre total de services effectués",
    )
    meilleure_serie: int = Field(
        0,
        description="Plus longue série de services consécutifs",
    )
    detail_services_par_set: list[ServiceSetDetail] = Field(default_factory=list)

    sets_joues: int = 0
    sets_titulaire: int = 0
    presence_par_set: list[PresenceSet] = Field(default_factory=list)

    temps_jeu_estime: Optional[float] = Field(
        None,
        description="Temps de jeu estimé en minutes",
    )
    temps_jeu_par_set: dict[int, float] = Field(
        default_factory=dict,
        description="Temps estimé par set (minutes)",
    )

    nb_entrees: int = 0
    nb_sorties: int = 0
    nb_changements_total: int = Field(0, description="Total entrées + sorties")

    temps_morts_provoques: int = Field(
        0,
        description="Temps morts adverses pris pendant une série de service du joueur",
    )

    sanctions: list[str] = Field(default_factory=list)

    est_calcul_libero: bool = Field(False, description="Stats calculées en mode libéro")
    joueurs_remplaces: list[str] = Field(
        default_factory=list,
        description="Numéros des joueurs remplacés par le libéro",
    )
    remplace_par_libero: bool = Field(
        False,
        description="Joueur remplacé par un libéro en zone arrière",
    )


class JoueurStatsAggregated(BaseModel):
    """Statistiques agrégées d'un joueur sur plusieurs matchs."""

    nom: str
    prenom: str
    licence: str

    matchs_joues: int = 0
    matchs_victoires: int = 0
    matchs_defaites: int = 0

    total_sets_joues: int = 0
    total_sets_titulaire: int = 0

    total_points_gagnes: int = 0
    total_points_gagnes_service: int = 0
    total_points_gagnes_sideout: int = 0
    total_points_perdus: int = 0
    total_points_joues: int = 0
    ratio_points_gagnes_global: float = 0.0
    break_point_ratio_global: float = 0.0
    ratio_points_gagnes_sideout_global: float = 0.0

    total_services: int = 0
    total_series_service: int = 0
    max_serie_service: int = 0
    moyenne_services_par_serie: float = 0.0
    total_tours_service: int = 0
    meilleure_serie_service: int = 0
    moyenne_points_par_tour: float = 0.0

    total_temps_jeu: float = 0.0
    moyenne_temps_par_match: float = 0.0

    total_entrees: int = 0
    total_sorties: int = 0

    total_temps_morts_provoques: int = 0
    moyenne_temps_morts_par_match: float = 0.0

    role_principal_global: Optional[str] = None
    roles_possibles_global: list[str] = Field(default_factory=list)
    role_distribution_matchs: dict[str, int] = Field(default_factory=dict)
    role_scores_moyens: dict[str, float] = Field(default_factory=dict)
    role_confiance_global: float = 0.0
    role_stabilite_pct: float = 0.0

    total_sanctions: int = 0
