"""
Modèles de données Pydantic pour PyVolley.

Ces modèles représentent les données métier et sont utilisés pour :
- La validation des données entrantes
- La sérialisation/désérialisation JSON
- La documentation automatique de l'API
"""

import re
from datetime import date as datetime_date, datetime, time as datetime_time
from typing import Optional, Any
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, field_validator

from pyvolley.shared.match_scores import resolve_match_score


# ============== Enums ==============

from pyvolley.core.constants import (
    Categorie,
    Genre,
    Niveau,
    RoleArbitre,
    RoleJoueur,
    TypeSanction,
)


# ============== Modèles de base ==============

class PyVolleyModel(BaseModel):
    """Modèle de base avec configuration commune."""
    
    model_config = ConfigDict(
        from_attributes=True,
        populate_by_name=True,
        str_strip_whitespace=True,
    )


# ============== Joueur ==============

class JoueurBase(PyVolleyModel):
    """Données de base d'un joueur."""
    licence: str = Field(..., min_length=1, max_length=10, description="Numéro de licence FFVB (peut être '0' pour joueurs non licenciés)")
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


# ============== Ligue & Comité ==============

class Ligue(PyVolleyModel):
    """Ligue régionale de volleyball."""
    id: Optional[int] = None
    code: str = Field(..., description="Code ligue à 2 chiffres (ex: 13, 09)")
    nom: str = Field(..., min_length=2)
    telephone: Optional[str] = None
    email: Optional[str] = None
    site_web: Optional[str] = None
    adresse_siege: Optional[str] = None
    president: Optional[str] = None


class Comite(PyVolleyModel):
    """Comité départemental de volleyball."""
    id: Optional[int] = None
    code: str = Field(..., description="Code comité à 3 chiffres (ex: 075, 059)")
    numero_departement: Optional[str] = None
    nom: str = Field(..., min_length=2)
    ligue_id: Optional[int] = None
    ligue_code: Optional[str] = None
    telephone: Optional[str] = None
    email: Optional[str] = None
    site_web: Optional[str] = None
    adresse_siege: Optional[str] = None


# ============== Club & Équipe ==============

class Club(PyVolleyModel):
    """Club de volleyball."""
    id: Optional[int] = None
    nom: str = Field(..., min_length=2)
    nom_court: Optional[str] = None
    code: Optional[str] = None
    code_ffvb: Optional[str] = None
    ville: Optional[str] = None
    departement: Optional[str] = None
    ligue: Optional[str] = None
    ligue_id: Optional[int] = None
    comite_id: Optional[int] = None
    adresse_siege: Optional[str] = None
    code_postal_siege: Optional[str] = None
    ville_siege: Optional[str] = None
    email: Optional[str] = None
    site_web: Optional[str] = None
    telephone: Optional[str] = None
    couleurs: Optional[str] = None
    president: Optional[str] = None
    correspondant_nom: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None

    @field_validator("nom", mode="before")
    @classmethod
    def validate_nom(cls, v: Any) -> str:
        if v is None:
            return ""
        s = str(v).strip()
        return re.sub(r"^[,\-._/\\;:'\"\s]+|[,\-._/\\;:'\"\s]+$", "", s).strip()


class Equipe(PyVolleyModel):
    """Équipe participant à une compétition."""
    id: Optional[int] = None
    nom: str = Field(..., min_length=2)
    nom_court: Optional[str] = None
    club_nom: Optional[str] = None  # Nom du club extrait du nom d'équipe
    numero_equipe: Optional[int] = None  # 1, 2, 3... si multiple équipes du club
    club_id: Optional[int] = None
    club: Optional[Club] = None
    niveau: Optional[str] = None  # Elite, Nationale, Régionale, ...
    division: Optional[str] = None  # N2, R1, D1, ...
    capitaine: Optional[str] = Field(None, description="Numéro de maillot du capitaine")
    joueurs: list[Joueur] = Field(default_factory=list)
    liberos: list[Joueur] = Field(default_factory=list)
    officiels: list["Officiel"] = Field(default_factory=list)
    entraineur: Optional[str] = None
    assistant: Optional[str] = None

    @field_validator("nom", mode="before")
    @classmethod
    def validate_nom(cls, v: Any) -> str:
        if v is None:
            return ""
        s = str(v).strip()
        cleaned = re.sub(r"^[,\-._/\\;:'\"\s]+|[,\-._/\\;:'\"\s]+$", "", s).strip()
        if len(cleaned) < 2:
            raise ValueError("Le nom d'équipe doit contenir au moins 2 caractères")
        return cleaned


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

    @property
    def nb_changements(self) -> int:
        return len(self.changements)

    @property
    def nb_timeouts(self) -> int:
        return len(self.timeouts)

    @property
    def nb_services(self) -> int:
        return sum(len(scores) for scores in self.services.values())


class Set(PyVolleyModel):
    """Données d'un set de volleyball.

    Les formations et timeouts sont stockés uniquement dans
    ``equipe_a`` / ``equipe_b`` (``SetTeamData``).
    Les propriétés ``formation_a``, ``formation_b``, ``timeouts_a``,
    ``timeouts_b`` sont des raccourcis en lecture seule qui délèguent
    vers les ``SetTeamData`` correspondants.
    """
    id: Optional[int] = None
    numero: int = Field(..., ge=1, le=5)
    score_a: Optional[int] = Field(None, ge=0)
    score_b: Optional[int] = Field(None, ge=0)
    debut: Optional[datetime_time] = None
    fin: Optional[datetime_time] = None
    duree_minutes: Optional[int] = None
    service_initial: Optional[str] = None  # 'A' ou 'B'
    equipe_a: Optional[SetTeamData] = None
    equipe_b: Optional[SetTeamData] = None

    # ── Raccourcis (lecture seule) ──

    @property
    def formation_a(self) -> Optional[Formation]:
        return self.equipe_a.formation if self.equipe_a else None

    @property
    def formation_b(self) -> Optional[Formation]:
        return self.equipe_b.formation if self.equipe_b else None

    @property
    def timeouts_a(self) -> list[TimeOut]:
        return self.equipe_a.timeouts if self.equipe_a else []

    @property
    def timeouts_b(self) -> list[TimeOut]:
        return self.equipe_b.timeouts if self.equipe_b else []

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

    def team_data(self, side: str) -> Optional["SetTeamData"]:
        """Retourne les données d'équipe pour un côté ('A' ou 'B')."""
        if side == "A":
            return self.equipe_a
        elif side == "B":
            return self.equipe_b
        return None


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
    categorie: Optional[str] = None
    genre: Optional[Genre] = None
    niveau: Optional[str] = None  # PRO, ELITE, NATIONALE, PRE_NATIONALE, REGIONALE, PRE_REGIONALE, DEPARTEMENTALE, LOISIR
    division: Optional[str] = None  # "1", "2", "3", etc.
    niveau_badge: Optional[str] = None  # "Pro A", "Elite", "N2", "Prénat", "R1", "D1", etc.
    niveau_rank: Optional[int] = None  # 0 à 18
    organisateur: Optional[str] = None  # "Compétitions Nationales", "Ligue ILE-DE-FRANCE", "Comité Seine Paris"
    
    # Équipes
    equipe_a: Optional[Equipe] = None
    equipe_b: Optional[Equipe] = None
    equipe_a_id: Optional[int] = None
    equipe_b_id: Optional[int] = None
    
    # Résultat
    vainqueur_nom: Optional[str] = None
    vainqueur_id: Optional[int] = None
    score_final: Optional[str] = None  # "3/1"
    score_export: Optional[str] = None
    score_pdf: Optional[str] = None
    sets_detail_export: list[dict] = Field(default_factory=list)
    sets_a: int = 0
    sets_b: int = 0
    duree_totale: Optional[str] = None
    match_joue: bool = False  # True si le match a effectivement été joué
    has_details: bool = False  # True si des détails de sets sont disponibles
    score_source: Optional[str] = None  # "pdf", "online", "manual"
    
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
        has_score_final = False
        for score_value in (self.score_final, self.score_effective):
            if not score_value or "/" not in score_value:
                continue
            left, right = score_value.split("/", 1)
            left = left.strip()
            right = right.strip()
            if left.isdigit() and right.isdigit():
                has_score_final = (int(left) + int(right)) > 0
            elif left.upper() == "P" or right.upper() == "P":
                has_score_final = True
            if has_score_final:
                break

        return bool(
            self.match_joue
            or self.vainqueur_nom
            or self.sets_a > 0
            or self.sets_b > 0
            or has_score_final
        )

    def equipe(self, side: str) -> Optional[Equipe]:
        """Retourne l'équipe pour un côté ('A' ou 'B')."""
        if side == "A":
            return self.equipe_a
        elif side == "B":
            return self.equipe_b
        return None

    @property
    def vainqueur(self) -> Optional[str]:
        """Retourne 'A' ou 'B' selon le vainqueur, ou None."""
        if self.sets_a > self.sets_b:
            return "A"
        elif self.sets_b > self.sets_a:
            return "B"
        return None

    @property
    def score_sets(self) -> Optional[str]:
        """Retourne le score en sets sous forme 'X-Y'."""
        if self.sets_a > 0 or self.sets_b > 0:
            return f"{self.sets_a}-{self.sets_b}"
        return None

    @property
    def score_resolution(self):
        return resolve_match_score(
            self.score_export,
            self.score_pdf,
            legacy_score=self.score_final,
        )

    @property
    def score_effective(self) -> Optional[str]:
        return self.score_resolution.score_effective

    @property
    def score_display(self) -> Optional[str]:
        return self.score_resolution.score_display

    @property
    def sets_detail_export_display(self) -> Optional[str]:
        """Chaîne formatée des sets du scraper (ex: '25-20, 16-25, 25-21, 25-18')."""
        if not self.sets_detail_export:
            return None
        parts = []
        for s in self.sets_detail_export:
            sa = s.get("score_a")
            sb = s.get("score_b")
            if sa is not None and sb is not None:
                parts.append(f"{sa}-{sb}")
        return ", ".join(parts) if parts else None

    @property
    def sets_detail_pdf_display(self) -> Optional[str]:
        """Chaîne formatée des sets du parser PDF (ex: '25-20, 18-25, 25-22, 23-25, 15-12')."""
        if not self.sets:
            return None
        parts = []
        for s in sorted(self.sets, key=lambda item: item.numero):
            if s.score_a is not None and s.score_b is not None:
                parts.append(f"{s.score_a}-{s.score_b}")
        return ", ".join(parts) if parts else None

    @property
    def score_divergence(self) -> dict:
        """Détaille la divergence éventuelle entre le scraper et le parser."""
        score_res = self.score_resolution
        score_sets_diff = bool(score_res.conflict)

        detail_export_str = self.sets_detail_export_display
        detail_pdf_str = self.sets_detail_pdf_display

        sets_detail_diff = False
        if detail_export_str and detail_pdf_str:
            sets_detail_diff = (detail_export_str != detail_pdf_str)

        has_divergence = score_sets_diff or sets_detail_diff
        return {
            "has_divergence": has_divergence,
            "score_sets_divergent": score_sets_diff,
            "sets_detail_divergent": sets_detail_diff,
            "score_scraper": self.score_export,
            "score_parser": self.score_pdf,
            "sets_scraper": detail_export_str,
            "sets_parser": detail_pdf_str,
            "score_effective": score_res.score_effective,
        }

    @property
    def score_conflict(self) -> bool:
        return self.score_divergence["has_divergence"]

    def invert_sides(self) -> "Match":
        """Retourne une copie du match avec les équipes A et B inversées."""
        return invert_match_sides(self)


def invert_match_sides(match: Match) -> Match:
    """Inverse complètement les côtés A et B d'un match (équipes, scores, sets, sanctions).

    Utile lorsqu'une feuille de match PDF a assigné l'équipe visiteuse comme Équipe A
    et l'équipe receveuse comme Équipe B (selon le toss / table de marque), afin de
    réaligner le match sur l'ordre officiel du calendrier / base de données.
    """
    def _swap_score_str(score_str: Optional[str]) -> Optional[str]:
        if not score_str:
            return score_str
        for sep in ("/", "-"):
            if sep in score_str:
                parts = score_str.split(sep, 1)
                return f"{parts[1].strip()}{sep}{parts[0].strip()}"
        return score_str

    # 1. Inverser les sets
    inverted_sets = []
    for s in match.sets:
        inv_eq_a = None
        if s.equipe_b:
            inv_timeouts_a = [
                TimeOut(score_a=to.score_b, score_b=to.score_a)
                for to in s.equipe_b.timeouts
            ]
            inv_changements_a = [
                Changement(
                    joueur_entrant=chg.joueur_entrant,
                    joueur_sortant=chg.joueur_sortant,
                    position=chg.position,
                    score_a=chg.score_b,
                    score_b=chg.score_a,
                )
                for chg in s.equipe_b.changements
            ]
            inv_eq_a = SetTeamData(
                formation=s.equipe_b.formation,
                timeouts=inv_timeouts_a,
                changements=inv_changements_a,
                services=dict(s.equipe_b.services) if s.equipe_b.services else {},
            )

        inv_eq_b = None
        if s.equipe_a:
            inv_timeouts_b = [
                TimeOut(score_a=to.score_b, score_b=to.score_a)
                for to in s.equipe_a.timeouts
            ]
            inv_changements_b = [
                Changement(
                    joueur_entrant=chg.joueur_entrant,
                    joueur_sortant=chg.joueur_sortant,
                    position=chg.position,
                    score_a=chg.score_b,
                    score_b=chg.score_a,
                )
                for chg in s.equipe_a.changements
            ]
            inv_eq_b = SetTeamData(
                formation=s.equipe_a.formation,
                timeouts=inv_timeouts_b,
                changements=inv_changements_b,
                services=dict(s.equipe_a.services) if s.equipe_a.services else {},
            )

        srv = s.service_initial
        if srv == "A":
            srv = "B"
        elif srv == "B":
            srv = "A"

        inv_set = Set(
            id=s.id,
            numero=s.numero,
            score_a=s.score_b,
            score_b=s.score_a,
            debut=s.debut,
            fin=s.fin,
            duree_minutes=s.duree_minutes,
            service_initial=srv,
            equipe_a=inv_eq_a,
            equipe_b=inv_eq_b,
        )
        inverted_sets.append(inv_set)

    # 2. Inverser les sanctions
    inverted_sanctions = []
    for sanc in match.sanctions:
        s_eq = sanc.equipe
        if s_eq == "A":
            s_eq = "B"
        elif s_eq == "B":
            s_eq = "A"
        inverted_sanctions.append(
            Sanction(
                id=sanc.id,
                type=sanc.type,
                set_numero=sanc.set_numero,
                equipe=s_eq,
                joueur_numero=sanc.joueur_numero,
                joueur_id=sanc.joueur_id,
                score_a=sanc.score_b,
                score_b=sanc.score_a,
            )
        )

    # 3. Inverser les scores texte
    inv_score_final = _swap_score_str(match.score_final)
    if not inv_score_final and (match.sets_a or match.sets_b):
        inv_score_final = f"{match.sets_b}/{match.sets_a}"

    inv_score_pdf = _swap_score_str(match.score_pdf)
    inv_score_export = _swap_score_str(match.score_export)

    # 4. Inverser vainqueur_id si relié à une équipe
    new_vainqueur_id = match.vainqueur_id
    if match.vainqueur_id:
        if match.vainqueur_id == match.equipe_a_id:
            new_vainqueur_id = match.equipe_b_id
        elif match.vainqueur_id == match.equipe_b_id:
            new_vainqueur_id = match.equipe_a_id

    inv_sets_detail_export = []
    if match.sets_detail_export:
        for s in match.sets_detail_export:
            s_copy = dict(s)
            s_copy["score_a"], s_copy["score_b"] = s_copy.get("score_b"), s_copy.get("score_a")
            inv_sets_detail_export.append(s_copy)

    return match.model_copy(
        update={
            "equipe_a": match.equipe_b,
            "equipe_b": match.equipe_a,
            "equipe_a_id": match.equipe_b_id,
            "equipe_b_id": match.equipe_a_id,
            "sets_a": match.sets_b,
            "sets_b": match.sets_a,
            "score_final": inv_score_final,
            "score_pdf": inv_score_pdf,
            "score_export": inv_score_export,
            "sets_detail_export": inv_sets_detail_export,
            "vainqueur_id": new_vainqueur_id,
            "sets": inverted_sets,
            "sanctions": inverted_sanctions,
        }
    )


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
