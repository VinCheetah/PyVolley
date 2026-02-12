"""
Modèles de données Pydantic pour PyVolley.

Ces modèles représentent les données métier et sont utilisés pour :
- La validation des données entrantes
- La sérialisation/désérialisation JSON
- La documentation automatique de l'API
"""

from datetime import date as datetime_date, datetime, time as datetime_time
from typing import Optional
from enum import Enum

from pydantic import BaseModel, Field, field_validator


# ============== Enums ==============

class Genre(str, Enum):
    """Genre de la compétition."""
    MASCULIN = "MASCULIN"
    FEMININ = "FEMININ"
    MIXTE = "MIXTE"


class Categorie(str, Enum):
    """Catégorie d'âge."""
    SENIOR = "SENIOR"
    M21 = "M21"
    M20 = "M20"
    M18 = "M18"
    M17 = "M17"
    M15 = "M15"
    M13 = "M13"
    VETERAN = "VETERAN"


class TypeSanction(str, Enum):
    """Type de sanction."""
    AVERTISSEMENT = "A"  # Carton jaune
    PENALITE = "P"       # Carton rouge = point adverse
    EXPULSION = "E"      # Exclusion du set
    DISQUALIFICATION = "D"  # Exclusion du match


class RoleArbitre(str, Enum):
    """Rôle de l'arbitre."""
    PREMIER = "1er"
    SECOND = "2ème"
    MARQUEUR = "Marqueur"
    MARQUEUR_ASSISTANT = "Marqueur assistant"
    RESPONSABLE_SALLE = "Responsable de salle"
    JUGE_LIGNE = "Juge de ligne"


# ============== Modèles de base ==============

class PyVolleyModel(BaseModel):
    """Modèle de base avec configuration commune."""
    
    class Config:
        from_attributes = True
        populate_by_name = True
        str_strip_whitespace = True


# ============== Joueur ==============

class JoueurBase(PyVolleyModel):
    """Données de base d'un joueur."""
    licence: str = Field(..., min_length=6, max_length=10, description="Numéro de licence FFVB")
    nom: str = Field(..., min_length=1, description="Nom de famille")
    prenom: str = Field(..., min_length=1, description="Prénom")
    
    @property
    def nom_complet(self) -> str:
        return f"{self.nom} {self.prenom}"


class Joueur(JoueurBase):
    """Joueur complet avec identifiant."""
    id: Optional[int] = None
    numero: Optional[str] = Field(None, description="Numéro de maillot")
    est_capitaine: bool = False
    est_libero: bool = False
    
    @field_validator("licence")
    @classmethod
    def validate_licence(cls, v: str) -> str:
        if not v.isdigit():
            raise ValueError("La licence doit contenir uniquement des chiffres")
        return v


class JoueurStats(Joueur):
    """Joueur avec statistiques agrégées."""
    matchs_joues: int = 0
    sets_joues: int = 0
    victoires: int = 0
    defaites: int = 0
    
    @property
    def taux_victoire(self) -> float:
        if self.matchs_joues == 0:
            return 0.0
        return self.victoires / self.matchs_joues


# ============== Club & Équipe ==============

class Club(PyVolleyModel):
    """Club de volleyball."""
    id: Optional[int] = None
    nom: str = Field(..., min_length=2)
    nom_court: Optional[str] = None
    code: Optional[str] = None
    ville: Optional[str] = None
    departement: Optional[str] = None


class Equipe(PyVolleyModel):
    """Équipe participant à une compétition."""
    id: Optional[int] = None
    nom: str = Field(..., min_length=2)
    nom_court: Optional[str] = None
    club_nom: Optional[str] = None  # Nom du club extrait du nom d'équipe
    numero_equipe: Optional[int] = None  # 1, 2, 3... si multiple équipes du club
    club_id: Optional[int] = None
    club: Optional[Club] = None
    joueurs: list[Joueur] = Field(default_factory=list)
    liberos: list[Joueur] = Field(default_factory=list)
    officiels: list["Officiel"] = Field(default_factory=list)
    entraineur: Optional[str] = None
    assistant: Optional[str] = None


# ============== Arbitre ==============

class Arbitre(PyVolleyModel):
    """Arbitre officiel."""
    id: Optional[int] = None
    licence: Optional[str] = None
    nom: str
    prenom: Optional[str] = None
    ligue: Optional[str] = None
    role: RoleArbitre = RoleArbitre.PREMIER
    
    @property
    def nom_complet(self) -> str:
        if self.prenom:
            return f"{self.nom} {self.prenom}"
        return self.nom


# ============== Officiel d'équipe ==============

class Officiel(PyVolleyModel):
    """Officiel d'équipe (EA, EB, MA, MB, KA, KB)."""
    role: str
    nom: str
    prenom: Optional[str] = None
    licence: Optional[str] = None

    @property
    def nom_complet(self) -> str:
        if self.prenom:
            return f"{self.nom} {self.prenom}"
        return self.nom


# ============== Sanction ==============

class Sanction(PyVolleyModel):
    """Sanction donnée pendant un match."""
    id: Optional[int] = None
    type: TypeSanction
    set_numero: int = Field(..., ge=1, le=5)
    equipe: str  # 'A' ou 'B'
    joueur_numero: Optional[str] = None
    joueur_id: Optional[int] = None
    score_a: Optional[int] = None
    score_b: Optional[int] = None


# ============== Formation & Set ==============

class Formation(PyVolleyModel):
    """Formation de départ pour un set (6 positions)."""
    position_1: Optional[str] = None  # Arrière droit (serveur)
    position_2: Optional[str] = None  # Avant droit
    position_3: Optional[str] = None  # Avant centre
    position_4: Optional[str] = None  # Avant gauche
    position_5: Optional[str] = None  # Arrière gauche
    position_6: Optional[str] = None  # Arrière centre
    
    def as_list(self) -> list[Optional[str]]:
        return [
            self.position_1, self.position_2, self.position_3,
            self.position_4, self.position_5, self.position_6
        ]
    
    def as_dict(self) -> dict[str, Optional[str]]:
        return {
            "I": self.position_1, "II": self.position_2, "III": self.position_3,
            "IV": self.position_4, "V": self.position_5, "VI": self.position_6
        }


class TimeOut(PyVolleyModel):
    """Temps mort demandé."""
    score_a: int
    score_b: int


class Changement(PyVolleyModel):
    """Changement de joueur pendant un set."""
    joueur_entrant: str
    joueur_sortant: Optional[str] = None
    position: Optional[int] = None
    score_a: Optional[int] = None
    score_b: Optional[int] = None


class SetTeamData(PyVolleyModel):
    """Données d'équipe pour un set (formations, temps morts, changements)."""
    formation: Optional[Formation] = None
    timeouts: list[TimeOut] = Field(default_factory=list)
    changements: list[Changement] = Field(default_factory=list)
    services: dict[int, list[int]] = Field(default_factory=dict)


class Set(PyVolleyModel):
    """Données d'un set de volleyball."""
    id: Optional[int] = None
    numero: int = Field(..., ge=1, le=5)
    score_a: Optional[int] = Field(None, ge=0)
    score_b: Optional[int] = Field(None, ge=0)
    debut: Optional[datetime_time] = None
    fin: Optional[datetime_time] = None
    duree_minutes: Optional[int] = None
    service_initial: Optional[str] = None  # 'A' ou 'B'
    formation_a: Optional[Formation] = None
    formation_b: Optional[Formation] = None
    timeouts_a: list[TimeOut] = Field(default_factory=list)
    timeouts_b: list[TimeOut] = Field(default_factory=list)
    equipe_a: Optional[SetTeamData] = None
    equipe_b: Optional[SetTeamData] = None
    
    @property
    def vainqueur(self) -> Optional[str]:
        if self.score_a is not None and self.score_b is not None:
            if self.score_a > self.score_b:
                return "A"
            elif self.score_b > self.score_a:
                return "B"
        return None
    
    @property
    def score_str(self) -> str:
        return f"{self.score_a}-{self.score_b}"


# ============== Match ==============

class MatchBase(PyVolleyModel):
    """Données de base d'un match."""
    code_match: str = Field(..., description="Code unique du match (ex: PMAA001)")
    date: Optional[datetime_date] = None
    heure: Optional[datetime_time] = None
    lieu: Optional[str] = None
    salle: Optional[str] = None


class Match(MatchBase):
    """Match complet de volleyball."""
    id: Optional[int] = None
    
    # Compétition
    ligue: Optional[str] = None
    competition: Optional[str] = None  # Nom complet ("EMA - ELITE MASCULINE - POULE A")
    competition_code: Optional[str] = None  # Code de la poule ("EMA")
    journee: Optional[str] = None
    saison: Optional[str] = None  # "2024-2025"
    categorie: Optional[Categorie] = None
    genre: Optional[Genre] = None
    
    # Équipes
    equipe_a: Optional[Equipe] = None
    equipe_b: Optional[Equipe] = None
    equipe_a_id: Optional[int] = None
    equipe_b_id: Optional[int] = None
    
    # Résultat
    vainqueur_nom: Optional[str] = None
    vainqueur_id: Optional[int] = None
    score_final: Optional[str] = None  # "3/1"
    sets_a: int = 0
    sets_b: int = 0
    duree_totale: Optional[str] = None
    
    # Détails
    sets: list[Set] = Field(default_factory=list)
    arbitres: list[Arbitre] = Field(default_factory=list)
    sanctions: list[Sanction] = Field(default_factory=list)
    remarques: Optional[str] = None
    
    # Métadonnées
    source_pdf: Optional[str] = None
    parsed_at: Optional[datetime] = None
    
    @property
    def is_played(self) -> bool:
        return bool(self.vainqueur_nom or self.sets_a > 0 or self.sets_b > 0)


# ============== Saison ==============

class Saison(PyVolleyModel):
    """Saison sportive."""
    id: Optional[int] = None
    code: str = Field(..., pattern=r"^\d{4}-\d{4}$")  # "2024-2025"
    debut: datetime_date
    fin: datetime_date
    
    @property
    def annee_debut(self) -> int:
        return int(self.code.split("-")[0])
    
    @property
    def annee_fin(self) -> int:
        return int(self.code.split("-")[1])


# ============== Recherche ==============

class SearchResult(PyVolleyModel):
    """Résultat de recherche."""
    type: str  # "joueur", "club", "equipe", "match"
    id: int
    nom: str
    details: Optional[str] = None
    score: float = 0.0  # Score de pertinence


class SearchQuery(PyVolleyModel):
    """Requête de recherche."""
    query: str = Field(..., min_length=2)
    types: list[str] = Field(default_factory=lambda: ["joueur", "club", "equipe"])
    saisons: list[str] = Field(default_factory=list)
    ligues: list[str] = Field(default_factory=list)
    limit: int = Field(default=20, ge=1, le=100)
