"""
Modèles SQLAlchemy pour la base de données PyVolley.

Schéma optimisé pour les données volleyball FFVB avec relations claires :
  Saison → Competition → Poule → Match
  Club → Equipe (par saison)
  Joueur ←→ Participation ←→ Match
  Arbitre ←→ ArbitreMatch ←→ Match

Chaque entité a un identifiant naturel (code, licence) en plus de la PK auto.
"""

from datetime import datetime as dt
from datetime import date as dt_date
from datetime import time as dt_time
from typing import Optional, List

from sqlalchemy import (
    Integer, String, Boolean, Date, Time, DateTime, Float,
    Text, JSON, ForeignKey, Table, Column, UniqueConstraint, Index,
)
from sqlalchemy.orm import DeclarativeBase, relationship, Mapped, mapped_column

from pyvolley.shared.match_scores import resolve_match_score


class Base(DeclarativeBase):
    """Classe de base pour tous les modèles."""
    pass


# =====================================================================
# Personne
# =====================================================================

class PersonneDB(Base):
    """Personne référencée dans le système (joueur, officiel, etc.)."""
    __tablename__ = "personnes"

    id: Mapped[int] = mapped_column(primary_key=True)
    licence: Mapped[Optional[str]] = mapped_column(String(20), nullable=True, index=True)
    nom: Mapped[str] = mapped_column(String(100), index=True)
    prenom: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    categorie: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)  # joueur, officiel, arbitre...
    created_at: Mapped[dt] = mapped_column(DateTime, default=dt.now)
    updated_at: Mapped[dt] = mapped_column(DateTime, default=dt.now, onupdate=dt.now)

    joueurs: Mapped[List["JoueurDB"]] = relationship(back_populates="personne")
    officiels_match: Mapped[List["OfficielMatchDB"]] = relationship(back_populates="personne")

    __table_args__ = (
        Index("ix_personnes_nom_prenom", "nom", "prenom"),
    )

    @property
    def nom_complet(self) -> str:
        if self.prenom:
            return f"{self.nom} {self.prenom}"
        return self.nom

    def __repr__(self) -> str:
        return f"<Personne {self.nom_complet} ({self.licence or 'sans-licence'})>"


# =====================================================================
# Saison
# =====================================================================

class SaisonDB(Base):
    """Saison sportive (ex: 2024-2025)."""
    __tablename__ = "saisons"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(9), unique=True, index=True)  # "2024-2025"
    nom: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    date_debut: Mapped[Optional[dt_date]] = mapped_column(Date, nullable=True)
    date_fin: Mapped[Optional[dt_date]] = mapped_column(Date, nullable=True)

    # Relations
    competitions: Mapped[List["CompetitionDB"]] = relationship(
        back_populates="saison", cascade="all, delete-orphan"
    )
    matchs: Mapped[List["MatchDB"]] = relationship(back_populates="saison")
    equipes: Mapped[List["EquipeDB"]] = relationship(back_populates="saison")

    def __repr__(self) -> str:
        return f"<Saison {self.code}>"


# =====================================================================
# Entité FFVB (organisatrice : ligue, comité, nationale)
# =====================================================================

class EntiteFFVBDB(Base):
    """Entité organisatrice FFVB (ligue, comité, nationale)."""
    __tablename__ = "entites_ffvb"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(20), unique=True, index=True)  # "ABCCS", "LIRA"
    nom: Mapped[str] = mapped_column(String(200))
    type: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)  # "nationale", "ligue", "comite"

    # Relations
    competitions: Mapped[List["CompetitionDB"]] = relationship(back_populates="entite")

    def __repr__(self) -> str:
        return f"<EntiteFFVB {self.code} ({self.type})>"


# =====================================================================
# Club
# =====================================================================

class ClubDB(Base):
    """Club de volleyball (entité permanente).

    Les champs d'adressier (couleurs, président, correspondant, adresse, etc.)
    sont enrichis automatiquement depuis l'endpoint ``adressier_pdf.php``
    de la FFVB lors du scraping Phase 1.
    """
    __tablename__ = "clubs"

    id: Mapped[int] = mapped_column(primary_key=True)
    nom: Mapped[str] = mapped_column(String(200), index=True)
    nom_court: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    code_ffvb: Mapped[Optional[str]] = mapped_column(String(20), nullable=True, unique=True)
    ville: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    departement: Mapped[Optional[str]] = mapped_column(String(5), nullable=True)
    ligue: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    couleurs: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)

    # Dirigeants
    president: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    entraineur: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    entraineur_adjoint: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)

    # Correspondant (contact principal)
    correspondant_nom: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    correspondant_adresse: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    correspondant_ville: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    correspondant_telephone: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    correspondant_portable: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    correspondant_email: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)

    # Logo externe (synchronisé depuis Volleybox)
    logo_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)

    # Coordonnées géographiques (pour la carte interactive)
    latitude: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    longitude: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    # Relations
    equipes: Mapped[List["EquipeDB"]] = relationship(back_populates="club")
    aliases: Mapped[List["ClubAliasDB"]] = relationship(
        back_populates="club", cascade="all, delete-orphan"
    )
    salles: Mapped[List["SalleClubDB"]] = relationship(
        back_populates="club", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<Club {self.nom}>"


class SalleClubDB(Base):
    """Salle d'un club (depuis l'adressier FFVB).

    Un club peut avoir jusqu'à 2 salles (S1 et S2 dans l'adressier).
    """
    __tablename__ = "salles_club"

    id: Mapped[int] = mapped_column(primary_key=True)
    club_id: Mapped[int] = mapped_column(ForeignKey("clubs.id", ondelete="CASCADE"))
    numero: Mapped[int] = mapped_column(Integer)  # 1 ou 2

    nom: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    adresse: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    ville: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    telephone: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    sol: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    capacite: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    transport: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)

    # Coordonnées géographiques (pour la carte interactive)
    latitude: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    longitude: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    club: Mapped["ClubDB"] = relationship(back_populates="salles")

    __table_args__ = (
        UniqueConstraint("club_id", "numero", name="uq_salle_club_numero"),
    )

    def __repr__(self) -> str:
        return f"<SalleClub {self.nom} (club_id={self.club_id})>"


class ClubAliasDB(Base):
    """Alias / variantes de noms de clubs (pour le matching)."""
    __tablename__ = "club_aliases"

    id: Mapped[int] = mapped_column(primary_key=True)
    alias: Mapped[str] = mapped_column(String(200), unique=True, index=True)
    club_id: Mapped[int] = mapped_column(ForeignKey("clubs.id", ondelete="CASCADE"))

    club: Mapped["ClubDB"] = relationship(back_populates="aliases")

    def __repr__(self) -> str:
        return f"<ClubAlias '{self.alias}' → Club #{self.club_id}>"


# =====================================================================
# Compétition
# =====================================================================

class CompetitionDB(Base):
    """Compétition (championnat, coupe, etc.) pour une saison donnée."""
    __tablename__ = "competitions"

    id: Mapped[int] = mapped_column(primary_key=True)
    nom: Mapped[str] = mapped_column(String(300))
    code_competition: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)

    # Caractéristiques
    genre: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    categorie: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    niveau: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    division: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    niveau_badge: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    niveau_rank: Mapped[int] = mapped_column(Integer, default=-1)

    # Foreign keys
    saison_id: Mapped[int] = mapped_column(ForeignKey("saisons.id"))
    entite_id: Mapped[Optional[int]] = mapped_column(ForeignKey("entites_ffvb.id"), nullable=True)

    # Relations
    saison: Mapped["SaisonDB"] = relationship(back_populates="competitions")
    entite: Mapped[Optional["EntiteFFVBDB"]] = relationship(back_populates="competitions")
    poules: Mapped[List["PouleDB"]] = relationship(
        back_populates="competition", cascade="all, delete-orphan"
    )
    matchs: Mapped[List["MatchDB"]] = relationship(back_populates="competition")
    equipes: Mapped[List["EquipeDB"]] = relationship(back_populates="competition")

    __table_args__ = (
        UniqueConstraint("nom", "saison_id", "genre", "categorie", name="uq_competition_nom_saison_genre_cat"),
        Index("ix_competitions_saison", "saison_id"),
        Index("ix_competitions_genre_categorie", "genre", "categorie"),
    )

    def __repr__(self) -> str:
        return f"<Competition {self.code_competition or self.nom}>"


# =====================================================================
# Poule
# =====================================================================

class PouleDB(Base):
    """Poule / division au sein d'une compétition."""
    __tablename__ = "poules"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(20))  # "EMA", "PMA", "1FA"
    nom: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    tour: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)  # Tour number (1, 2, 3... or 99 for finals)

    # Cache du classement complet sérialisé (O(1))
    classement_cache: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    classement_updated_at: Mapped[Optional[dt]] = mapped_column(DateTime, nullable=True)

    competition_id: Mapped[int] = mapped_column(ForeignKey("competitions.id", ondelete="CASCADE"))

    competition: Mapped["CompetitionDB"] = relationship(back_populates="poules")
    matchs: Mapped[List["MatchDB"]] = relationship(back_populates="poule")

    __table_args__ = (
        UniqueConstraint("code", "competition_id", name="uq_poule_code_competition"),
        Index("ix_poules_tour", "competition_id", "tour"),
    )

    def __repr__(self) -> str:
        return f"<Poule {self.code}>"


# =====================================================================
# Équipe (instance d'un club dans une saison)
# =====================================================================

class EquipeDB(Base):
    """Équipe participant à une compétition pour une saison donnée.

    Représente l'inscription d'un club dans une compétition.
    Ex: 'GRENOBLE VUC' dans 'Elite Masculine 2025-2026'.
    """
    __tablename__ = "equipes"

    id: Mapped[int] = mapped_column(primary_key=True)
    nom: Mapped[str] = mapped_column(String(200), index=True)
    numero_equipe: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    genre: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    categorie: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    niveau: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)  # Elite, Nationale, Régionale, Départementale...
    division: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)  # N2, N3, R1, R2, D1...
    niveau_badge: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    niveau_rank: Mapped[int] = mapped_column(Integer, default=-1)

    # Foreign keys
    club_id: Mapped[Optional[int]] = mapped_column(ForeignKey("clubs.id"), nullable=True)
    saison_id: Mapped[Optional[int]] = mapped_column(ForeignKey("saisons.id"), nullable=True)
    competition_id: Mapped[Optional[int]] = mapped_column(ForeignKey("competitions.id"), nullable=True)

    # Relations
    club: Mapped[Optional["ClubDB"]] = relationship(back_populates="equipes")
    saison: Mapped[Optional["SaisonDB"]] = relationship(back_populates="equipes")
    competition: Mapped[Optional["CompetitionDB"]] = relationship(back_populates="equipes")
    participations: Mapped[List["ParticipationMatchDB"]] = relationship(back_populates="equipe")
    saison_stats: Mapped[List["EquipeSaisonStatsDB"]] = relationship(
        back_populates="equipe", cascade="all, delete-orphan"
    )


    __table_args__ = (
        UniqueConstraint("nom", "saison_id", "competition_id", name="uq_equipe_nom_saison_competition"),
        Index("ix_equipes_club_saison", "club_id", "saison_id"),
        Index("ix_equipes_competition", "competition_id"),
    )

    def __repr__(self) -> str:
        return f"<Equipe {self.nom}>"


# =====================================================================
# Joueur
# =====================================================================

class JoueurDB(Base):
    """Joueur de volleyball (identifié par licence FFVB)."""
    __tablename__ = "joueurs"

    id: Mapped[int] = mapped_column(primary_key=True)
    licence: Mapped[str] = mapped_column(String(20), unique=True, index=True)
    nom: Mapped[str] = mapped_column(String(100), index=True)
    prenom: Mapped[str] = mapped_column(String(100))
    personne_id: Mapped[Optional[int]] = mapped_column(ForeignKey("personnes.id"), nullable=True)

    # Relations
    participations: Mapped[List["ParticipationMatchDB"]] = relationship(back_populates="joueur")
    match_stats: Mapped[List["JoueurMatchStatsDB"]] = relationship(
        back_populates="joueur", cascade="all, delete-orphan"
    )
    saison_stats: Mapped[List["JoueurSaisonStatsDB"]] = relationship(
        back_populates="joueur", cascade="all, delete-orphan"
    )
    carriere_stats: Mapped[Optional["JoueurCarriereStatsDB"]] = relationship(
        back_populates="joueur", uselist=False, cascade="all, delete-orphan"
    )
    personne: Mapped[Optional["PersonneDB"]] = relationship(back_populates="joueurs")

    __table_args__ = (
        Index("ix_joueurs_nom_prenom", "nom", "prenom"),
    )

    @property
    def nom_complet(self) -> str:
        return f"{self.nom} {self.prenom}"

    def __repr__(self) -> str:
        return f"<Joueur {self.nom} {self.prenom} ({self.licence})>"


# =====================================================================
# Match
# =====================================================================

class MatchDB(Base):
    """Match de volleyball."""
    __tablename__ = "matchs"

    id: Mapped[int] = mapped_column(primary_key=True)
    code_match: Mapped[str] = mapped_column(String(30), index=True)

    # Date et lieu
    date_match: Mapped[Optional[dt_date]] = mapped_column(Date, nullable=True)
    heure_match: Mapped[Optional[str]] = mapped_column(String(8), nullable=True)
    salle: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)

    # Journée
    journee: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)

    # Codes clubs FFVB (depuis l'export CSV)
    club_a_code_ffvb: Mapped[Optional[str]] = mapped_column(String(20), nullable=True, index=True)
    club_b_code_ffvb: Mapped[Optional[str]] = mapped_column(String(20), nullable=True, index=True)

    # Foreign keys
    saison_id: Mapped[Optional[int]] = mapped_column(ForeignKey("saisons.id"), nullable=True)
    competition_id: Mapped[Optional[int]] = mapped_column(ForeignKey("competitions.id"), nullable=True)
    poule_id: Mapped[Optional[int]] = mapped_column(ForeignKey("poules.id"), nullable=True)
    equipe_a_id: Mapped[Optional[int]] = mapped_column(ForeignKey("equipes.id"), nullable=True)
    equipe_b_id: Mapped[Optional[int]] = mapped_column(ForeignKey("equipes.id"), nullable=True)

    # Résultat
    vainqueur: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    score_sets: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)  # "3/1"
    score_export: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)
    score_pdf: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)
    sets_equipe_a: Mapped[int] = mapped_column(Integer, default=0)
    sets_equipe_b: Mapped[int] = mapped_column(Integer, default=0)
    duree_totale: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)

    # Match status
    match_joue: Mapped[bool] = mapped_column(Boolean, default=False)
    has_details: Mapped[bool] = mapped_column(Boolean, default=False)
    score_source: Mapped[Optional[str]] = mapped_column(
        String(20), nullable=True
    )  # "pdf", "online", "manual"

    # Forfait
    forfait: Mapped[bool] = mapped_column(Boolean, default=False)

    # Remarques
    remarques: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Pipeline status
    parsing_status: Mapped[str] = mapped_column(
        String(20), default="discovered"
    )  # "discovered", "downloaded", "parsed", "error"
    source_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)

    # Classification sportive et niveau du match
    genre: Mapped[Optional[str]] = mapped_column(String(20), nullable=True, index=True)
    categorie: Mapped[Optional[str]] = mapped_column(String(20), nullable=True, index=True)
    niveau: Mapped[Optional[str]] = mapped_column(String(50), nullable=True, index=True)
    division: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    niveau_badge: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    niveau_rank: Mapped[int] = mapped_column(Integer, default=-1, index=True)

    # Métadonnées
    source_pdf: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    parsed_at: Mapped[Optional[dt]] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[dt] = mapped_column(DateTime, default=dt.now)
    updated_at: Mapped[dt] = mapped_column(DateTime, default=dt.now, onupdate=dt.now)

    # Relations
    saison: Mapped[Optional["SaisonDB"]] = relationship(back_populates="matchs")
    competition: Mapped[Optional["CompetitionDB"]] = relationship(back_populates="matchs")
    poule: Mapped[Optional["PouleDB"]] = relationship(back_populates="matchs")
    equipe_a: Mapped[Optional["EquipeDB"]] = relationship(foreign_keys=[equipe_a_id])
    equipe_b: Mapped[Optional["EquipeDB"]] = relationship(foreign_keys=[equipe_b_id])
    sets: Mapped[List["SetDB"]] = relationship(
        back_populates="match", cascade="all, delete-orphan", order_by="SetDB.numero"
    )
    arbitrages: Mapped[List["ArbitreMatchDB"]] = relationship(
        back_populates="match", cascade="all, delete-orphan"
    )
    sanctions: Mapped[List["SanctionDB"]] = relationship(
        back_populates="match", cascade="all, delete-orphan"
    )
    participations: Mapped[List["ParticipationMatchDB"]] = relationship(
        back_populates="match", cascade="all, delete-orphan"
    )
    joueur_stats: Mapped[List["JoueurMatchStatsDB"]] = relationship(
        back_populates="match", cascade="all, delete-orphan"
    )
    officiels: Mapped[List["OfficielMatchDB"]] = relationship(
        back_populates="match", cascade="all, delete-orphan"
    )

    __table_args__ = (
        UniqueConstraint("code_match", "saison_id", name="uq_match_code_saison"),
        Index("ix_matchs_date", "date_match"),
        Index("ix_matchs_competition", "competition_id"),
        Index("ix_matchs_has_details", "has_details", "saison_id"),
        Index("ix_matchs_parsing_status", "parsing_status"),
        # Partial index pour les matchs sans saison (empêche les doublons
        # quand saison_id IS NULL)
        Index(
            "ix_matchs_code_no_saison",
            "code_match",
            unique=True,
            sqlite_where=Column("saison_id").is_(None),
            postgresql_where=Column("saison_id").is_(None),
        ),
    )

    @property
    def is_played(self) -> bool:
        sets_total = (self.sets_equipe_a or 0) + (self.sets_equipe_b or 0)
        has_score_sets = False
        score_candidates = [self.score_sets, self.score_effective]
        for score_value in score_candidates:
            if not score_value or "/" not in score_value:
                continue
            left, right = score_value.split("/", 1)
            left = left.strip()
            right = right.strip()
            if left.isdigit() and right.isdigit():
                has_score_sets = (int(left) + int(right)) > 0
            elif left.upper() == "P" or right.upper() == "P":
                has_score_sets = True
            if has_score_sets:
                break

        return bool(
            self.match_joue
            or self.forfait
            or self.vainqueur is not None
            or sets_total > 0
            or has_score_sets
        )

    @property
    def statut(self) -> str:
        """Statut calculé du match.

        Retourne l'un des états suivants :
        - 'forfait'       : le match a été déclaré forfait
        - 'joué'          : le match a été joué (résultat disponible)
        - 'à_venir'       : le match est programmé dans le futur
        - 'sans_résultat' : le match est passé mais aucun résultat n'a été saisi
        """
        if self.forfait:
            return "forfait"
        if self.is_played:
            return "joué"
        if self.date_match and self.date_match > dt_date.today():
            return "à_venir"
        return "sans_résultat"

    @property
    def score_resolution(self):
        return resolve_match_score(
            self.score_export,
            self.score_pdf,
            legacy_score=self.score_sets,
        )

    @property
    def score_effective(self) -> Optional[str]:
        return self.score_resolution.score_effective

    @property
    def score_display(self) -> Optional[str]:
        return self.score_resolution.score_display

    @property
    def score_conflict(self) -> bool:
        return self.score_resolution.conflict

    @property
    def score_primary_source(self) -> Optional[str]:
        return self.score_resolution.primary_source

    @property
    def score_secondary_source(self) -> Optional[str]:
        return self.score_resolution.secondary_source

    def __repr__(self) -> str:
        return f"<Match {self.code_match}>"


# =====================================================================
# Set
# =====================================================================

class SetDB(Base):
    """Set d'un match."""
    __tablename__ = "sets"

    id: Mapped[int] = mapped_column(primary_key=True)
    numero: Mapped[int] = mapped_column(Integer)

    match_id: Mapped[int] = mapped_column(ForeignKey("matchs.id", ondelete="CASCADE"), index=True)

    score_a: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    score_b: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    heure_debut: Mapped[Optional[str]] = mapped_column(String(8), nullable=True)
    heure_fin: Mapped[Optional[str]] = mapped_column(String(8), nullable=True)
    duree_minutes: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    service_initial: Mapped[Optional[str]] = mapped_column(String(1), nullable=True)

    # Services data from PDF parsing (position → list of cumulative scores
    # at each service loss). Stored as JSON: {"1": [3, 12], "4": [8, 20]}.
    services_a: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    services_b: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)

    # Relations
    match: Mapped["MatchDB"] = relationship(back_populates="sets")
    formations: Mapped[List["FormationDB"]] = relationship(
        back_populates="set_", cascade="all, delete-orphan"
    )
    changements: Mapped[List["ChangementDB"]] = relationship(
        back_populates="set_", cascade="all, delete-orphan"
    )
    timeouts: Mapped[List["TimeoutDB"]] = relationship(
        back_populates="set_", cascade="all, delete-orphan"
    )

    @property
    def vainqueur(self) -> Optional[str]:
        if self.score_a is not None and self.score_b is not None:
            return "A" if self.score_a > self.score_b else "B"
        return None

    def __repr__(self) -> str:
        return f"<Set {self.numero}: {self.score_a}-{self.score_b}>"


# =====================================================================
# Formation
# =====================================================================

class FormationDB(Base):
    """Formation de départ pour un set (6 positions)."""
    __tablename__ = "formations"

    id: Mapped[int] = mapped_column(primary_key=True)
    set_id: Mapped[int] = mapped_column(ForeignKey("sets.id", ondelete="CASCADE"), index=True)
    equipe: Mapped[str] = mapped_column(String(1))

    position_1: Mapped[Optional[str]] = mapped_column(String(3), nullable=True)
    position_2: Mapped[Optional[str]] = mapped_column(String(3), nullable=True)
    position_3: Mapped[Optional[str]] = mapped_column(String(3), nullable=True)
    position_4: Mapped[Optional[str]] = mapped_column(String(3), nullable=True)
    position_5: Mapped[Optional[str]] = mapped_column(String(3), nullable=True)
    position_6: Mapped[Optional[str]] = mapped_column(String(3), nullable=True)

    set_: Mapped["SetDB"] = relationship(back_populates="formations")

    __table_args__ = (
        UniqueConstraint("set_id", "equipe", name="uq_formation_set_equipe"),
    )


# =====================================================================
# Changement
# =====================================================================

class ChangementDB(Base):
    """Changement de joueur pendant un set."""
    __tablename__ = "changements"

    id: Mapped[int] = mapped_column(primary_key=True)
    set_id: Mapped[int] = mapped_column(ForeignKey("sets.id", ondelete="CASCADE"), index=True)
    equipe: Mapped[str] = mapped_column(String(1))

    joueur_entrant: Mapped[str] = mapped_column(String(3))
    joueur_sortant: Mapped[Optional[str]] = mapped_column(String(3), nullable=True)
    position: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    score_a: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    score_b: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    set_: Mapped["SetDB"] = relationship(back_populates="changements")


# =====================================================================
# Timeout
# =====================================================================

class TimeoutDB(Base):
    """Temps mort demandé pendant un set."""
    __tablename__ = "timeouts"

    id: Mapped[int] = mapped_column(primary_key=True)
    set_id: Mapped[int] = mapped_column(ForeignKey("sets.id", ondelete="CASCADE"), index=True)
    equipe: Mapped[str] = mapped_column(String(1))

    score_a: Mapped[int] = mapped_column(Integer)
    score_b: Mapped[int] = mapped_column(Integer)

    set_: Mapped["SetDB"] = relationship(back_populates="timeouts")


# =====================================================================
# Arbitre
# =====================================================================

class ArbitreDB(Base):
    """Arbitre officiel (identifié par licence ou nom)."""
    __tablename__ = "arbitres"

    id: Mapped[int] = mapped_column(primary_key=True)
    licence: Mapped[Optional[str]] = mapped_column(String(20), unique=True, nullable=True, index=True)
    nom: Mapped[str] = mapped_column(String(100), index=True)
    prenom: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    ligue: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    comite_departemental: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)

    # Relations
    arbitrages: Mapped[List["ArbitreMatchDB"]] = relationship(back_populates="arbitre")

    @property
    def nom_complet(self) -> str:
        if self.prenom:
            return f"{self.nom} {self.prenom}"
        return self.nom

    def __repr__(self) -> str:
        return f"<Arbitre {self.nom_complet}>"


class ArbitreMatchDB(Base):
    """Association Arbitre-Match avec rôle."""
    __tablename__ = "arbitre_match"

    id: Mapped[int] = mapped_column(primary_key=True)
    arbitre_id: Mapped[int] = mapped_column(ForeignKey("arbitres.id", ondelete="CASCADE"))
    match_id: Mapped[int] = mapped_column(ForeignKey("matchs.id", ondelete="CASCADE"), index=True)
    role: Mapped[str] = mapped_column(String(30))

    arbitre: Mapped["ArbitreDB"] = relationship(back_populates="arbitrages")
    match: Mapped["MatchDB"] = relationship(back_populates="arbitrages")

    __table_args__ = (
        UniqueConstraint("arbitre_id", "match_id", "role", name="uq_arbitre_match_role"),
    )


# =====================================================================
# Sanction
# =====================================================================

class SanctionDB(Base):
    """Sanction donnée pendant un match."""
    __tablename__ = "sanctions"

    id: Mapped[int] = mapped_column(primary_key=True)
    match_id: Mapped[int] = mapped_column(ForeignKey("matchs.id", ondelete="CASCADE"), index=True)

    type_sanction: Mapped[str] = mapped_column(String(1))
    set_numero: Mapped[int] = mapped_column(Integer)
    equipe: Mapped[str] = mapped_column(String(1))
    joueur_numero: Mapped[Optional[str]] = mapped_column(String(5), nullable=True)
    score_a: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    score_b: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    match: Mapped["MatchDB"] = relationship(back_populates="sanctions")

    def __repr__(self) -> str:
        return f"<Sanction {self.type_sanction} set {self.set_numero}>"


# =====================================================================
# Participation Match
# =====================================================================

class ParticipationMatchDB(Base):
    """Participation d'un joueur à un match pour une équipe."""
    __tablename__ = "participations_match"

    id: Mapped[int] = mapped_column(primary_key=True)
    match_id: Mapped[int] = mapped_column(ForeignKey("matchs.id", ondelete="CASCADE"))
    joueur_id: Mapped[int] = mapped_column(ForeignKey("joueurs.id", ondelete="CASCADE"))
    equipe_id: Mapped[int] = mapped_column(ForeignKey("equipes.id", ondelete="CASCADE"))

    numero_maillot: Mapped[Optional[str]] = mapped_column(String(5), nullable=True)
    side: Mapped[Optional[str]] = mapped_column(String(1), nullable=True)  # 'A' ou 'B'
    est_capitaine: Mapped[bool] = mapped_column(Boolean, default=False)
    est_libero: Mapped[bool] = mapped_column(Boolean, default=False)

    match: Mapped["MatchDB"] = relationship(back_populates="participations")
    joueur: Mapped["JoueurDB"] = relationship(back_populates="participations")
    equipe: Mapped["EquipeDB"] = relationship(back_populates="participations")

    __table_args__ = (
        UniqueConstraint("match_id", "joueur_id", name="uq_participation"),
        Index("ix_participation_match_joueur", "match_id", "joueur_id"),
        Index("ix_participation_joueur", "joueur_id"),
        Index("ix_participation_equipe", "equipe_id"),
        Index("ix_participation_match_side", "match_id", "side"),
    )

    def __repr__(self) -> str:
        return f"<Participation joueur={self.joueur_id} match={self.match_id}>"


# =====================================================================
# Officiel Match (entraîneur, manager, etc.)
# =====================================================================

class OfficielMatchDB(Base):
    """Officiel d'équipe pour un match (entraîneur, assistant, etc.)."""
    __tablename__ = "officiels_match"

    id: Mapped[int] = mapped_column(primary_key=True)
    match_id: Mapped[int] = mapped_column(ForeignKey("matchs.id", ondelete="CASCADE"), index=True)
    equipe: Mapped[str] = mapped_column(String(1))  # 'A' ou 'B'
    role: Mapped[str] = mapped_column(String(10))  # 'EA', 'EB', 'MA', 'MB', 'KA', 'KB'
    nom: Mapped[str] = mapped_column(String(100))
    prenom: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    licence: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    personne_id: Mapped[Optional[int]] = mapped_column(ForeignKey("personnes.id"), nullable=True)

    match: Mapped["MatchDB"] = relationship(back_populates="officiels")
    personne: Mapped[Optional["PersonneDB"]] = relationship(back_populates="officiels_match")

    def __repr__(self) -> str:
        return f"<Officiel {self.role} {self.nom}>"


# =====================================================================
# Statistiques détaillées joueur par match
# =====================================================================

class JoueurMatchStatsDB(Base):
    """Statistiques détaillées persistées d'un joueur pour un match.

    Les statistiques sont calculées à partir des données détaillées de feuille
    de match (sets, formations, changements, services). Stocke les métriques
    directement dans des colonnes SQL typées sans dépendance à un blob JSON.
    """
    __tablename__ = "joueur_match_stats"

    id: Mapped[int] = mapped_column(primary_key=True)
    match_id: Mapped[int] = mapped_column(ForeignKey("matchs.id", ondelete="CASCADE"), index=True)
    joueur_id: Mapped[int] = mapped_column(ForeignKey("joueurs.id", ondelete="CASCADE"), index=True)
    equipe_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("equipes.id", ondelete="CASCADE"), nullable=True, index=True
    )

    # Contexte joueur / match
    numero: Mapped[Optional[str]] = mapped_column(String(5), nullable=True)
    side: Mapped[Optional[str]] = mapped_column(String(1), nullable=True)  # 'A' ou 'B'
    est_capitaine: Mapped[bool] = mapped_column(Boolean, default=False)
    est_libero: Mapped[bool] = mapped_column(Boolean, default=False)
    victoire: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    score_match: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)

    # Points & Ratios
    points_gagnes: Mapped[int] = mapped_column(Integer, default=0)
    points_perdus: Mapped[int] = mapped_column(Integer, default=0)
    points_joues: Mapped[int] = mapped_column(Integer, default=0)
    points_gagnes_service: Mapped[int] = mapped_column(Integer, default=0)
    points_gagnes_sideout: Mapped[int] = mapped_column(Integer, default=0)
    ratio_points_gagnes: Mapped[float] = mapped_column(Float, default=0.0)
    break_point_ratio: Mapped[float] = mapped_column(Float, default=0.0)
    sideout_contribution_ratio: Mapped[float] = mapped_column(Float, default=0.0)

    # Services & Séries
    services: Mapped[int] = mapped_column(Integer, default=0)
    series: Mapped[int] = mapped_column(Integer, default=0)
    max_serie: Mapped[int] = mapped_column(Integer, default=0)
    moyenne_services_par_serie: Mapped[float] = mapped_column(Float, default=0.0)
    temps_morts_provoques: Mapped[int] = mapped_column(Integer, default=0)

    # Sets & Présence
    sets_joues: Mapped[int] = mapped_column(Integer, default=0)
    sets_titulaire: Mapped[int] = mapped_column(Integer, default=0)
    temps_jeu_estime: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    nb_entrees: Mapped[int] = mapped_column(Integer, default=0)
    nb_sorties: Mapped[int] = mapped_column(Integer, default=0)

    # Rôles & Inférences
    role_principal: Mapped[Optional[str]] = mapped_column(String(30), nullable=True, index=True)
    role_confiance: Mapped[float] = mapped_column(Float, default=0.0)
    roles_possibles: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    role_scores: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    indices_roles: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)

    # Détails structurés complémentaires
    detail_services_par_set: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    presence_par_set: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    temps_jeu_par_set: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)

    # Horodatages
    match_updated_at: Mapped[Optional[dt]] = mapped_column(DateTime, nullable=True)
    computed_at: Mapped[dt] = mapped_column(DateTime, default=dt.now)

    match: Mapped["MatchDB"] = relationship(back_populates="joueur_stats")
    joueur: Mapped["JoueurDB"] = relationship(back_populates="match_stats")
    equipe: Mapped[Optional["EquipeDB"]] = relationship()

    __table_args__ = (
        UniqueConstraint("match_id", "joueur_id", name="uq_joueur_match_stats"),
        Index("ix_joueur_match_stats_match", "match_id"),
        Index("ix_joueur_match_stats_joueur", "joueur_id"),
        Index("ix_joueur_match_stats_equipe", "equipe_id"),
        Index("ix_joueur_match_stats_points_gagnes", "points_gagnes"),
        Index("ix_joueur_match_stats_services", "services"),
        Index("ix_joueur_match_stats_role", "role_principal"),
    )

    def to_detailed_stats(self) -> "JoueurMatchDetailedStats":
        """Convertit l'entité SQL en modèle Pydantic d'analyse."""
        from pyvolley.analysis.models import JoueurMatchDetailedStats
        return JoueurMatchDetailedStats(
            numero=self.numero or "",
            nom=self.joueur.nom if self.joueur else "",
            prenom=self.joueur.prenom if self.joueur and self.joueur.prenom else "",
            licence=self.joueur.licence if self.joueur and self.joueur.licence else "",
            equipe=self.equipe.nom if self.equipe else "",
            side=self.side or "",
            est_libero=self.est_libero,
            est_capitaine=self.est_capitaine,
            victoire=bool(self.victoire),
            score_match=self.score_match,
            points_gagnes=self.points_gagnes,
            points_gagnes_service=self.points_gagnes_service,
            points_perdus=self.points_perdus,
            points_joues=self.points_joues,
            points_gagnes_sideout=self.points_gagnes_sideout,
            ratio_points_gagnes=self.ratio_points_gagnes,
            break_point_ratio=self.break_point_ratio,
            sideout_contribution_ratio=self.sideout_contribution_ratio,
            services=self.services,
            serie=self.series,
            max_serie=self.max_serie,
            moyenne_services_par_serie=self.moyenne_services_par_serie,
            nb_services=self.services,
            meilleure_serie=self.max_serie,
            detail_services_par_set=self.detail_services_par_set or [],
            sets_joues=self.sets_joues,
            sets_titulaire=self.sets_titulaire,
            presence_par_set=self.presence_par_set or [],
            temps_jeu_estime=self.temps_jeu_estime,
            temps_jeu_par_set=self.temps_jeu_par_set or {},
            nb_entrees=self.nb_entrees,
            nb_sorties=self.nb_sorties,
            nb_changements_total=self.nb_entrees + self.nb_sorties,
            temps_morts_provoques=self.temps_morts_provoques,
            role_principal=self.role_principal,
            roles_possibles=self.roles_possibles or [],
            role_scores=self.role_scores or {},
            role_confiance=self.role_confiance,
            indices_roles=self.indices_roles or [],
        )

    def as_dict(self) -> dict:
        """Retourne un dictionnaire complet des métriques de match."""
        return {
            "joueur_id": self.joueur_id,
            "match_id": self.match_id,
            "equipe_id": self.equipe_id,
            "numero": self.numero,
            "side": self.side,
            "est_capitaine": self.est_capitaine,
            "est_libero": self.est_libero,
            "victoire": self.victoire,
            "score_match": self.score_match,
            "points_gagnes": self.points_gagnes,
            "points_perdus": self.points_perdus,
            "points_joues": self.points_joues,
            "points_gagnes_service": self.points_gagnes_service,
            "points_gagnes_sideout": self.points_gagnes_sideout,
            "ratio_points_gagnes": self.ratio_points_gagnes,
            "break_point_ratio": self.break_point_ratio,
            "sideout_contribution_ratio": self.sideout_contribution_ratio,
            "services": self.services,
            "series": self.series,
            "max_serie": self.max_serie,
            "moyenne_services_par_serie": self.moyenne_services_par_serie,
            "sets_joues": self.sets_joues,
            "sets_titulaire": self.sets_titulaire,
            "temps_jeu_estime": self.temps_jeu_estime,
            "nb_entrees": self.nb_entrees,
            "nb_sorties": self.nb_sorties,
            "temps_morts_provoques": self.temps_morts_provoques,
            "role_principal": self.role_principal,
            "role_confiance": self.role_confiance,
            "roles_possibles": self.roles_possibles,
            "role_scores": self.role_scores,
            "indices_roles": self.indices_roles,
        }

    def __repr__(self) -> str:
        return f"<JoueurMatchStats joueur={self.joueur_id} match={self.match_id} pts={self.points_gagnes}>"



# =====================================================================
# Journal d'import (audit)
# =====================================================================

class ImportLogDB(Base):
    """Historique des opérations d'import en base de données.

    Chaque exécution de ``parse --save-db`` ou ``import_db`` crée une
    entrée qui résume ce qui a été fait : nombre de matchs importés,
    doublons ignorés, erreurs rencontrées, durée, etc.
    """
    __tablename__ = "import_logs"

    id: Mapped[int] = mapped_column(primary_key=True)

    # Quand et quoi
    started_at: Mapped[dt] = mapped_column(DateTime, default=dt.now)
    finished_at: Mapped[Optional[dt]] = mapped_column(DateTime, nullable=True)
    operation: Mapped[str] = mapped_column(String(30))  # "parse", "import", "complete-scores"
    source: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)  # chemin ou description

    # Compteurs
    total_attempted: Mapped[int] = mapped_column(Integer, default=0)
    imported: Mapped[int] = mapped_column(Integer, default=0)
    duplicates: Mapped[int] = mapped_column(Integer, default=0)
    errors: Mapped[int] = mapped_column(Integer, default=0)
    updated: Mapped[int] = mapped_column(Integer, default=0)

    # Détails (JSON sérialisé)
    error_details: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Statut
    status: Mapped[str] = mapped_column(String(20), default="running")  # running, success, partial, failed

    __table_args__ = (
        Index("ix_import_logs_started_at", "started_at"),
        Index("ix_import_logs_operation", "operation"),
    )

    def __repr__(self) -> str:
        return (
            f"<ImportLog {self.operation} {self.started_at:%Y-%m-%d %H:%M} "
            f"imported={self.imported} errors={self.errors} status={self.status}>"
        )


# =====================================================================
# Cache des statistiques pré-calculées
# =====================================================================

class StatsCacheDB(Base):
    """Résultats de statistiques pré-calculés et stockés en base.

    Chaque ligne correspond à une combinaison de filtres (saison, genre,
    catégorie, niveau, département). Les données JSON peuvent être servies
    directement par la route ``/palmares`` sans recalcul.

    La clé ``filter_key`` est la sérialisation canonique des filtres et
    sert d'identifiant naturel unique pour la mise à jour.
    """
    __tablename__ = "stats_cache"

    id: Mapped[int] = mapped_column(primary_key=True)

    # Clé unique représentant la combinaison de filtres
    filter_key: Mapped[str] = mapped_column(String(500), unique=True, index=True)

    # Résultats sérialisés (dict JSON retourné par get_all_stats)
    stats_data: Mapped[dict] = mapped_column(JSON, nullable=False)

    # Horodatage du calcul
    computed_at: Mapped[dt] = mapped_column(DateTime, default=dt.now)

    # Nombre de matchs présents lors du calcul (pour détection d'obsolescence)
    match_count: Mapped[int] = mapped_column(Integer, default=0)

    __table_args__ = (
        Index("ix_stats_cache_computed_at", "computed_at"),
    )

    def __repr__(self) -> str:
        return f"<StatsCache key={self.filter_key!r} computed={self.computed_at:%Y-%m-%d %H:%M}>"




# =====================================================================
# Statistiques agglomérées par joueur et par saison / compétition / équipe
# =====================================================================

class JoueurSaisonStatsDB(Base):
    """Statistiques agglomérées (rollup) d'un joueur pour une saison, compétition et équipe données.

    Permet des requêtes instantanées en O(1) pour les pages profils, classements par division,
    et palmarès sans rescanner l'intégralité des participations.
    """
    __tablename__ = "stats_joueur_saison"

    id: Mapped[int] = mapped_column(primary_key=True)
    joueur_id: Mapped[int] = mapped_column(ForeignKey("joueurs.id", ondelete="CASCADE"), index=True)
    saison_id: Mapped[int] = mapped_column(ForeignKey("saisons.id", ondelete="CASCADE"), index=True)
    competition_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("competitions.id", ondelete="CASCADE"), nullable=True, index=True
    )
    equipe_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("equipes.id", ondelete="CASCADE"), nullable=True, index=True
    )

    # Métriques de participation
    matchs_joues: Mapped[int] = mapped_column(Integer, default=0)
    matchs_titulaire: Mapped[int] = mapped_column(Integer, default=0)
    victoires: Mapped[int] = mapped_column(Integer, default=0)
    defaites: Mapped[int] = mapped_column(Integer, default=0)
    sets_joues: Mapped[int] = mapped_column(Integer, default=0)
    sets_titulaire: Mapped[int] = mapped_column(Integer, default=0)

    # Métriques de score & points
    points_gagnes: Mapped[int] = mapped_column(Integer, default=0)
    points_perdus: Mapped[int] = mapped_column(Integer, default=0)
    points_joues: Mapped[int] = mapped_column(Integer, default=0)
    points_service: Mapped[int] = mapped_column(Integer, default=0)
    points_sideout: Mapped[int] = mapped_column(Integer, default=0)

    # Services & Séries
    services: Mapped[int] = mapped_column(Integer, default=0)
    series: Mapped[int] = mapped_column(Integer, default=0)
    max_serie: Mapped[int] = mapped_column(Integer, default=0)
    moyenne_services_par_serie: Mapped[float] = mapped_column(Float, default=0.0)
    ratio_points_gagnes: Mapped[float] = mapped_column(Float, default=0.0)

    # Rôles
    role_principal: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)
    role_confiance: Mapped[float] = mapped_column(Float, default=0.0)
    roles_frequence: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    role_distribution: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)

    # Horodatage
    computed_at: Mapped[dt] = mapped_column(DateTime, default=dt.now)
    updated_at: Mapped[dt] = mapped_column(DateTime, default=dt.now, onupdate=dt.now)

    # Relations
    joueur: Mapped["JoueurDB"] = relationship(back_populates="saison_stats")
    saison: Mapped["SaisonDB"] = relationship()
    competition: Mapped[Optional["CompetitionDB"]] = relationship()
    equipe: Mapped[Optional["EquipeDB"]] = relationship()

    __table_args__ = (
        UniqueConstraint("joueur_id", "saison_id", "competition_id", "equipe_id", name="uq_stats_joueur_saison_comp_eq"),
        Index("ix_sjs_saison_competition", "saison_id", "competition_id"),
        Index("ix_sjs_joueur_saison", "joueur_id", "saison_id"),
        Index("ix_sjs_points_gagnes", "points_gagnes"),
        Index("ix_sjs_services", "services"),
    )

    def __repr__(self) -> str:
        return f"<JoueurSaisonStats joueur={self.joueur_id} saison={self.saison_id} pts={self.points_gagnes}>"


# =====================================================================
# Statistiques agglomérées carrière d'un joueur
# =====================================================================

class JoueurCarriereStatsDB(Base):
    """Synthèse globale sur l'ensemble de la carrière d'un joueur."""
    __tablename__ = "stats_joueur_carriere"

    id: Mapped[int] = mapped_column(primary_key=True)
    joueur_id: Mapped[int] = mapped_column(
        ForeignKey("joueurs.id", ondelete="CASCADE"), unique=True, index=True
    )

    total_matchs: Mapped[int] = mapped_column(Integer, default=0)
    total_victoires: Mapped[int] = mapped_column(Integer, default=0)
    total_defaites: Mapped[int] = mapped_column(Integer, default=0)
    total_sets: Mapped[int] = mapped_column(Integer, default=0)
    total_points_gagnes: Mapped[int] = mapped_column(Integer, default=0)
    total_points_joues: Mapped[int] = mapped_column(Integer, default=0)
    total_services: Mapped[int] = mapped_column(Integer, default=0)
    total_series: Mapped[int] = mapped_column(Integer, default=0)
    max_serie_carriere: Mapped[int] = mapped_column(Integer, default=0)
    max_points_match: Mapped[int] = mapped_column(Integer, default=0)

    clubs_frequentes_count: Mapped[int] = mapped_column(Integer, default=0)
    saisons_count: Mapped[int] = mapped_column(Integer, default=0)
    premier_match_date: Mapped[Optional[dt_date]] = mapped_column(Date, nullable=True)
    dernier_match_date: Mapped[Optional[dt_date]] = mapped_column(Date, nullable=True)

    # Estimations d'âge et niveau maximum atteint
    estimated_birth_year_min: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    estimated_max_age: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    best_category_label: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    max_niveau_label: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    max_niveau_rank: Mapped[int] = mapped_column(Integer, default=-1)

    # Rôles
    role_principal: Mapped[Optional[str]] = mapped_column(String(30), nullable=True, index=True)
    role_confiance: Mapped[float] = mapped_column(Float, default=0.0)
    roles_frequence: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    role_distribution: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)

    computed_at: Mapped[dt] = mapped_column(DateTime, default=dt.now)
    updated_at: Mapped[dt] = mapped_column(DateTime, default=dt.now, onupdate=dt.now)

    joueur: Mapped["JoueurDB"] = relationship(back_populates="carriere_stats")

    __table_args__ = (
        Index("ix_sjc_total_matchs", "total_matchs"),
        Index("ix_sjc_total_points", "total_points_gagnes"),
        Index("ix_sjc_role_principal", "role_principal"),
    )

    def __repr__(self) -> str:
        return f"<JoueurCarriereStats joueur={self.joueur_id} matchs={self.total_matchs} pts={self.total_points_gagnes}>"


# =====================================================================
# Statistiques agglomérées par équipe et par saison
# =====================================================================

class EquipeSaisonStatsDB(Base):
    """Statistiques agglomérées (rollup) d'une équipe pour une saison et compétition données."""
    __tablename__ = "stats_equipe_saison"

    id: Mapped[int] = mapped_column(primary_key=True)
    equipe_id: Mapped[int] = mapped_column(ForeignKey("equipes.id", ondelete="CASCADE"), index=True)
    saison_id: Mapped[int] = mapped_column(ForeignKey("saisons.id", ondelete="CASCADE"), index=True)
    competition_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("competitions.id", ondelete="CASCADE"), nullable=True, index=True
    )
    poule_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("poules.id", ondelete="CASCADE"), nullable=True, index=True
    )

    matchs_joues: Mapped[int] = mapped_column(Integer, default=0)
    victoires: Mapped[int] = mapped_column(Integer, default=0)
    defaites: Mapped[int] = mapped_column(Integer, default=0)
    victoires_domicile: Mapped[int] = mapped_column(Integer, default=0)
    victoires_exterieur: Mapped[int] = mapped_column(Integer, default=0)

    # Répartition des scores
    victoires_3_0: Mapped[int] = mapped_column(Integer, default=0)
    victoires_3_1: Mapped[int] = mapped_column(Integer, default=0)
    victoires_3_2: Mapped[int] = mapped_column(Integer, default=0)
    defaites_2_3: Mapped[int] = mapped_column(Integer, default=0)
    defaites_1_3: Mapped[int] = mapped_column(Integer, default=0)
    defaites_0_3: Mapped[int] = mapped_column(Integer, default=0)
    forfaits: Mapped[int] = mapped_column(Integer, default=0)

    # Sets & Points
    points_ffvb: Mapped[int] = mapped_column(Integer, default=0)
    rang: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    sets_pour: Mapped[int] = mapped_column(Integer, default=0)
    sets_contre: Mapped[int] = mapped_column(Integer, default=0)
    ratio_sets: Mapped[float] = mapped_column(Float, default=0.0)
    points_pour: Mapped[int] = mapped_column(Integer, default=0)
    points_contre: Mapped[int] = mapped_column(Integer, default=0)
    ratio_points: Mapped[float] = mapped_column(Float, default=0.0)

    # Séries
    serie_victoires_max: Mapped[int] = mapped_column(Integer, default=0)
    serie_en_cours: Mapped[int] = mapped_column(Integer, default=0)

    computed_at: Mapped[dt] = mapped_column(DateTime, default=dt.now)
    updated_at: Mapped[dt] = mapped_column(DateTime, default=dt.now, onupdate=dt.now)

    equipe: Mapped["EquipeDB"] = relationship(back_populates="saison_stats")
    saison: Mapped["SaisonDB"] = relationship()
    competition: Mapped[Optional["CompetitionDB"]] = relationship()
    poule: Mapped[Optional["PouleDB"]] = relationship()

    __table_args__ = (
        UniqueConstraint("equipe_id", "saison_id", "competition_id", name="uq_stats_equipe_saison_comp"),
        Index("ix_ses_saison_competition", "saison_id", "competition_id"),
        Index("ix_ses_victoires", "victoires"),
    )

    def __repr__(self) -> str:
        return f"<EquipeSaisonStats equipe={self.equipe_id} V/D={self.victoires}/{self.defaites}>"

