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


class PositionRotationStats(BaseModel):
    """Statistiques d'un joueur ou d'une équipe dans une position de rotation donnée (1 à 6)."""

    points_joues: int = 0
    points_gagnes: int = 0
    points_perdus: int = 0
    win_rate: float = 0.0


class RotationStats(BaseModel):
    """Statistiques ventilées par position de rotation sur le terrain (P1 à P6)."""

    p1: PositionRotationStats = Field(default_factory=PositionRotationStats)
    p2: PositionRotationStats = Field(default_factory=PositionRotationStats)
    p3: PositionRotationStats = Field(default_factory=PositionRotationStats)
    p4: PositionRotationStats = Field(default_factory=PositionRotationStats)
    p5: PositionRotationStats = Field(default_factory=PositionRotationStats)
    p6: PositionRotationStats = Field(default_factory=PositionRotationStats)

    def as_dict(self) -> dict[str, dict[str, float | int]]:
        return {
            "P1": self.p1.model_dump(),
            "P2": self.p2.model_dump(),
            "P3": self.p3.model_dump(),
            "P4": self.p4.model_dump(),
            "P5": self.p5.model_dump(),
            "P6": self.p6.model_dump(),
        }


class ClutchStats(BaseModel):
    """Statistiques dans les situations de score à enjeu / clutch."""

    # Égalité
    points_egalite: int = 0
    points_gagnes_egalite: int = 0
    win_rate_egalite: float = 0.0

    # Équipe en tête
    points_en_tete: int = 0
    points_gagnes_en_tete: int = 0
    win_rate_en_tete: float = 0.0

    # Équipe menée
    points_menee: int = 0
    points_gagnes_menee: int = 0
    win_rate_menee: float = 0.0

    # Money time (score >= 20 ou >= 12 au 5e set)
    points_money_time: int = 0
    points_gagnes_money_time: int = 0
    win_rate_money_time: float = 0.0

    # Balles de set adverses (sauvées)
    balles_de_set_adverse_total: int = 0
    balles_de_set_adverse_sauvees: int = 0
    win_rate_sauve_balle_set: float = 0.0

    # Balles de match adverses (sauvées)
    balles_de_match_adverse_total: int = 0
    balles_de_match_adverse_sauvees: int = 0
    win_rate_sauve_balle_match: float = 0.0

    # Balles de set en faveur de l'équipe (converties)
    balles_de_set_equipe_total: int = 0
    balles_de_set_equipe_converties: int = 0
    win_rate_balle_set_equipe: float = 0.0

    # Balles de match en faveur de l'équipe (converties)
    balles_de_match_equipe_total: int = 0
    balles_de_match_equipe_converties: int = 0
    win_rate_balle_match_equipe: float = 0.0

    # Séries de service sous haute pression
    max_serie_sauve_balle_set: int = 0
    max_serie_sauve_balle_match: int = 0


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
    sideout_win_rate: float = Field(
        0.0,
        description="Taux de points gagnés en réception (side-out gagne / points joués en réception)",
    )
    plus_minus: int = Field(
        0,
        description="Différentiel net de points (points_gagnes - points_perdus)",
    )
    points_joues_off: int = Field(
        0,
        description="Points joués par l'équipe pendant que le joueur est sur le banc",
    )
    points_gagnes_off: int = Field(
        0,
        description="Points gagnés par l'équipe pendant que le joueur est sur le banc",
    )
    ratio_points_gagnes_off: Optional[float] = Field(
        None,
        description="Ratio points gagnés de l'équipe sur le banc",
    )
    differentiel_points_gagnes: Optional[float] = Field(
        None,
        description="Différentiel net On/Off (ratio sur le terrain - ratio sur le banc)",
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
    max_services_set: int = Field(
        0,
        description="Nombre maximal de services effectués dans un seul set",
    )
    detail_services_par_set: list[ServiceSetDetail] = Field(default_factory=list)

    sets_joues: int = 0
    sets_gagnes: int = 0
    sets_perdus: int = 0
    sets_commences: int = 0
    sets_titulaire: int = 0
    sets_termines: int = 0
    titulaire_set_1: bool = False
    match_complet: bool = False
    match_non_joue: bool = False
    presence_relative: float = Field(
        0.0,
        description="Part des points disputés par l'équipe passés sur le terrain",
    )
    presence_par_set: list[PresenceSet] = Field(default_factory=list)

    temps_jeu_estime: Optional[float] = Field(
        None,
        description="Temps de jeu estimé en minutes (somme des ratios présence x durée du set)",
    )
    temps_jeu_par_set: dict[int, float] = Field(
        default_factory=dict,
        description="Temps estimé par set (minutes)",
    )

    nb_entrees: int = 0
    nb_sorties: int = 0
    nb_changements_total: int = Field(0, description="Total entrées + sorties")
    nb_entrees_sorties: int = Field(
        0,
        description="Nombre de fois entré en cours de set puis ressorti dans le même set",
    )
    nb_sorties_entrees: int = Field(
        0,
        description="Nombre de fois titulaire/présent sorti au banc puis ré-entré dans le même set",
    )

    rotations: RotationStats = Field(default_factory=RotationStats)
    clutch: ClutchStats = Field(default_factory=ClutchStats)

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
    total_matchs_complets: int = 0
    total_matchs_non_joues: int = 0
    total_titularisations_set_1: int = 0

    total_sets_joues: int = 0
    total_sets_gagnes: int = 0
    total_sets_perdus: int = 0
    total_sets_commences: int = 0
    total_sets_titulaire: int = 0
    total_sets_termines: int = 0
    presence_relative_moyenne: float = 0.0

    total_points_gagnes: int = 0
    total_points_gagnes_service: int = 0
    total_points_gagnes_sideout: int = 0
    total_points_perdus: int = 0
    total_points_joues: int = 0
    total_plus_minus: int = 0
    ratio_points_gagnes_global: float = 0.0
    break_point_ratio_global: float = 0.0
    ratio_points_gagnes_sideout_global: float = 0.0
    sideout_win_rate_global: float = 0.0
    differentiel_points_gagnes_global: Optional[float] = None

    total_services: int = 0
    total_series_service: int = 0
    max_serie_service: int = 0
    max_services_set_record: int = 0
    moyenne_services_par_serie: float = 0.0
    total_tours_service: int = 0
    meilleure_serie_service: int = 0
    moyenne_points_par_tour: float = 0.0

    total_temps_jeu: float = 0.0
    moyenne_temps_par_match: float = 0.0
    moyenne_temps_par_set: float = 0.0

    total_entrees: int = 0
    total_sorties: int = 0
    total_entrees_sorties: int = 0
    total_sorties_entrees: int = 0

    rotations_globales: RotationStats = Field(default_factory=RotationStats)
    clutch_global: ClutchStats = Field(default_factory=ClutchStats)

    total_temps_morts_provoques: int = 0
    moyenne_temps_morts_par_match: float = 0.0

    role_principal_global: Optional[str] = None
    roles_possibles_global: list[str] = Field(default_factory=list)
    role_distribution_matchs: dict[str, int] = Field(default_factory=dict)
    role_scores_moyens: dict[str, float] = Field(default_factory=dict)
    role_confiance_global: float = 0.0
    role_stabilite_pct: float = 0.0

    total_sanctions: int = 0
