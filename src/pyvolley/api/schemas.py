"""
Schémas Pydantic pour les réponses API.
"""

from typing import Optional, List
from datetime import datetime, date as datetime_date
from pydantic import BaseModel, ConfigDict


# ============== Base Schemas ==============

class JoueurResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    licence: str
    nom: str
    prenom: str


class JoueurDetail(JoueurResponse):
    matchs_joues: int = 0
    equipes: List[str] = []
    saisons: List[str] = []
    capitaine_count: int = 0
    libero_count: int = 0


class ClubResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    nom: str
    nom_court: Optional[str] = None
    ville: Optional[str] = None
    departement: Optional[str] = None


class ClubDetail(ClubResponse):
    equipes_count: int = 0
    code_ffvb: Optional[str] = None


class EquipeResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    nom: str
    club_id: Optional[int] = None
    categorie: Optional[str] = None
    genre: Optional[str] = None


class EquipeDetail(EquipeResponse):
    club_nom: Optional[str] = None
    saison_code: Optional[str] = None
    matchs_count: int = 0
    victoires: int = 0
    defaites: int = 0


class ArbitreResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    nom: str
    prenom: Optional[str] = None
    licence: Optional[str] = None
    ligue: Optional[str] = None


class ArbitreDetail(ArbitreResponse):
    matchs_count: int = 0
    roles: dict = {}


class SaisonResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    code: str
    nom: Optional[str] = None
    date_debut: Optional[datetime_date] = None
    date_fin: Optional[datetime_date] = None


class CompetitionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    nom: str
    code_competition: Optional[str] = None
    genre: Optional[str] = None
    categorie: Optional[str] = None
    niveau: Optional[str] = None
    division: Optional[str] = None


class CompetitionDetail(CompetitionResponse):
    saison_code: Optional[str] = None
    entite_nom: Optional[str] = None
    matchs_count: int = 0
    equipes_count: int = 0


class SetResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    numero: int
    score_a: int
    score_b: int
    heure_debut: Optional[str] = None
    heure_fin: Optional[str] = None
    duree_minutes: Optional[int] = None
    service_initial: Optional[str] = None


class FormationResponse(BaseModel):
    equipe: str
    position_1: Optional[str] = None
    position_2: Optional[str] = None
    position_3: Optional[str] = None
    position_4: Optional[str] = None
    position_5: Optional[str] = None
    position_6: Optional[str] = None


class ChangementResponse(BaseModel):
    equipe: str
    joueur_entrant: str
    joueur_sortant: Optional[str] = None
    position: Optional[int] = None
    score_a: Optional[int] = None
    score_b: Optional[int] = None


class TimeoutResponse(BaseModel):
    equipe: str
    score_a: int
    score_b: int


class SanctionResponse(BaseModel):
    type_sanction: str
    set_numero: int
    equipe: str
    joueur_numero: Optional[str] = None
    score_a: Optional[int] = None
    score_b: Optional[int] = None


class ParticipationResponse(BaseModel):
    joueur_id: int
    joueur_nom: str
    joueur_prenom: str
    joueur_licence: str
    equipe_nom: str
    equipe_id: int
    numero_maillot: Optional[str] = None
    est_capitaine: bool = False
    est_libero: bool = False


class OfficielResponse(BaseModel):
    role: str
    nom: str
    prenom: Optional[str] = None
    licence: Optional[str] = None
    equipe: str


class ArbitreMatchResponse(BaseModel):
    arbitre_id: int
    nom: str
    prenom: Optional[str] = None
    role: str


class SetDetailResponse(SetResponse):
    formations: List[FormationResponse] = []
    changements: List[ChangementResponse] = []
    timeouts: List[TimeoutResponse] = []


class MatchResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    code_match: str
    date: Optional[datetime_date] = None
    heure: Optional[str] = None
    lieu: Optional[str] = None
    equipe_a_nom: str
    equipe_b_nom: str
    score_sets: Optional[str] = None
    score_export: Optional[str] = None
    score_pdf: Optional[str] = None
    score_effective: Optional[str] = None
    score_display: Optional[str] = None
    score_conflict: bool = False
    sets_equipe_a: int = 0
    sets_equipe_b: int = 0
    vainqueur: Optional[str] = None
    has_details: bool = False
    # Métadonnées de compétition (via relation)
    competition_nom: Optional[str] = None
    genre: Optional[str] = None
    categorie: Optional[str] = None
    journee: Optional[str] = None


class MatchDetail(MatchResponse):
    salle: Optional[str] = None
    saison_code: Optional[str] = None
    division_code: Optional[str] = None
    duree_totale: Optional[str] = None
    remarques: Optional[str] = None
    equipe_a_id: Optional[int] = None
    equipe_b_id: Optional[int] = None
    sets: List[SetDetailResponse] = []
    participations: List[ParticipationResponse] = []
    arbitres: List[ArbitreMatchResponse] = []
    officiels: List[OfficielResponse] = []
    sanctions: List[SanctionResponse] = []


# ============== Search Schemas ==============

class SearchResult(BaseModel):
    joueurs: List[JoueurResponse] = []
    clubs: List[ClubResponse] = []
    equipes: List[EquipeResponse] = []
    arbitres: List[ArbitreResponse] = []
    matchs: List[MatchResponse] = []
    total: int = 0


# ============== Stats Schemas ==============

class StatsOverview(BaseModel):
    total_matchs: int
    total_joueurs: int
    total_clubs: int
    total_equipes: int
    total_arbitres: int = 0
    total_competitions: int = 0
    saisons: List[str] = []
    matchs_par_saison: dict = {}
    matchs_par_mois: List[dict] = []
