"""
Schémas Pydantic pour les réponses API.
"""

from typing import Optional, List
from datetime import datetime, date as datetime_date
from pydantic import BaseModel, ConfigDict


# ============== Base Schemas ==============

class JoueurResponse(BaseModel):
    """Schéma de réponse pour un joueur."""
    model_config = ConfigDict(from_attributes=True)
    
    id: int
    licence: str
    nom: str
    prenom: str
    date_naissance: Optional[str] = None


class JoueurDetail(JoueurResponse):
    """Schéma détaillé d'un joueur avec stats."""
    matchs_joues: int = 0
    equipes: List[str] = []


class ClubResponse(BaseModel):
    """Schéma de réponse pour un club."""
    model_config = ConfigDict(from_attributes=True)
    
    id: int
    nom: str
    ligue: Optional[str] = None
    ville: Optional[str] = None


class ClubDetail(ClubResponse):
    """Schéma détaillé d'un club."""
    equipes_count: int = 0
    joueurs_count: int = 0


class EquipeResponse(BaseModel):
    """Schéma de réponse pour une équipe."""
    model_config = ConfigDict(from_attributes=True)
    
    id: int
    nom: str
    club_id: Optional[int] = None
    categorie: Optional[str] = None
    genre: Optional[str] = None


class EquipeDetail(EquipeResponse):
    """Schéma détaillé d'une équipe."""
    club_nom: Optional[str] = None
    matchs_count: int = 0
    victoires: int = 0
    defaites: int = 0


class SetResponse(BaseModel):
    """Schéma de réponse pour un set."""
    model_config = ConfigDict(from_attributes=True)
    
    numero: int
    score_a: int
    score_b: int
    heure_debut: Optional[str] = None
    heure_fin: Optional[str] = None


class MatchResponse(BaseModel):
    """Schéma de réponse pour un match."""
    model_config = ConfigDict(from_attributes=True)
    
    id: int
    code_match: str
    date: Optional[datetime_date] = None
    heure: Optional[str] = None
    lieu: Optional[str] = None
    equipe_a_nom: str
    equipe_b_nom: str
    score_final: Optional[str] = None
    vainqueur_nom: Optional[str] = None


class MatchDetail(MatchResponse):
    """Schéma détaillé d'un match."""
    salle: Optional[str] = None
    competition_nom: Optional[str] = None
    journee: Optional[str] = None
    duree_totale: Optional[str] = None
    sets: List[SetResponse] = []
    remarques: Optional[str] = None


# ============== Search Schemas ==============

class SearchQuery(BaseModel):
    """Schéma pour une requête de recherche."""
    q: str
    limit: int = 20
    offset: int = 0


class SearchResult(BaseModel):
    """Schéma pour les résultats de recherche."""
    joueurs: List[JoueurResponse] = []
    clubs: List[ClubResponse] = []
    equipes: List[EquipeResponse] = []
    matchs: List[MatchResponse] = []
    total: int = 0


# ============== Stats Schemas ==============

class StatsOverview(BaseModel):
    """Statistiques globales."""
    total_matchs: int
    total_joueurs: int
    total_clubs: int
    total_equipes: int
    saisons: List[str] = []


class JoueurStats(BaseModel):
    """Statistiques d'un joueur."""
    joueur: JoueurResponse
    matchs_joues: int
    sets_joues: int = 0
    equipes: List[str] = []
    saisons: List[str] = []


class EquipeStats(BaseModel):
    """Statistiques d'une équipe."""
    equipe: EquipeResponse
    matchs_joues: int
    victoires: int
    defaites: int
    sets_gagnes: int
    sets_perdus: int
    ratio: float = 0.0


# ============== Import Schemas ==============

class ImportRequest(BaseModel):
    """Requête d'import de données."""
    url: Optional[str] = None
    file_path: Optional[str] = None


class ImportResult(BaseModel):
    """Résultat d'un import."""
    total: int
    imported: int
    duplicates: int
    errors: List[str] = []
