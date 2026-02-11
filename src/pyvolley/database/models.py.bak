"""
Modèles SQLAlchemy pour la base de données.

Ces modèles représentent les tables de la base de données
et leurs relations. Compatible PostgreSQL et SQLite.
"""

from datetime import datetime as dt
from datetime import date as dt_date
from datetime import time as dt_time
from typing import Optional, List

from sqlalchemy import (
    Integer, String, Boolean, Date, Time, DateTime,
    Text, ForeignKey, Table, Column, UniqueConstraint, Index
)
from sqlalchemy.orm import DeclarativeBase, relationship, Mapped, mapped_column


class Base(DeclarativeBase):
    """Classe de base pour tous les modèles."""
    pass


# ============== Tables d'association ==============

joueur_equipe = Table(
    "joueur_equipe",
    Base.metadata,
    Column("joueur_id", Integer, ForeignKey("joueurs.id"), primary_key=True),
    Column("equipe_id", Integer, ForeignKey("equipes.id"), primary_key=True),
    Column("saison_id", Integer, ForeignKey("saisons.id"), nullable=True),
    Column("est_libero", Boolean, default=False),
)


# ============== Saison ==============

class SaisonDB(Base):
    """Saison sportive (ex: 2024-2025)."""
    __tablename__ = "saisons"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(9), unique=True)  # "2024-2025"
    nom: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)  # "Saison 2024-2025"
    date_debut: Mapped[Optional[dt_date]] = mapped_column(Date, nullable=True)
    date_fin: Mapped[Optional[dt_date]] = mapped_column(Date, nullable=True)

    # Relations
    competitions: Mapped[List["CompetitionDB"]] = relationship(back_populates="saison")
    matchs: Mapped[List["MatchDB"]] = relationship(back_populates="saison")

    def __repr__(self) -> str:
        return f"<Saison {self.code}>"


# ============== Club ==============

class ClubDB(Base):
    """Club de volleyball."""
    __tablename__ = "clubs"

    id: Mapped[int] = mapped_column(primary_key=True)
    nom: Mapped[str] = mapped_column(String(200), index=True)
    code: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    ville: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    ligue: Mapped[Optional[str]] = mapped_column(String(50), nullable=True, index=True)

    # Relations
    equipes: Mapped[List["EquipeDB"]] = relationship(back_populates="club")

    __table_args__ = (
        UniqueConstraint("nom", "ligue", name="uq_club_nom_ligue"),
        Index("ix_clubs_nom_ligue", "nom", "ligue"),
    )

    def __repr__(self) -> str:
        return f"<Club {self.nom}>"


# ============== Équipe ==============

class EquipeDB(Base):
    """Équipe participant à une compétition."""
    __tablename__ = "equipes"

    id: Mapped[int] = mapped_column(primary_key=True)
    nom: Mapped[str] = mapped_column(String(200), index=True)
    nom_court: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    categorie: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    genre: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)

    # Foreign keys
    club_id: Mapped[Optional[int]] = mapped_column(ForeignKey("clubs.id"), nullable=True)

    # Relations
    club: Mapped[Optional["ClubDB"]] = relationship(back_populates="equipes")
    joueurs: Mapped[List["JoueurDB"]] = relationship(
        secondary=joueur_equipe, back_populates="equipes"
    )
    participations: Mapped[List["ParticipationMatchDB"]] = relationship(back_populates="equipe")

    def __repr__(self) -> str:
        return f"<Equipe {self.nom}>"


# ============== Joueur ==============

class JoueurDB(Base):
    """Joueur de volleyball."""
    __tablename__ = "joueurs"

    id: Mapped[int] = mapped_column(primary_key=True)
    licence: Mapped[str] = mapped_column(String(20), unique=True, index=True)
    nom: Mapped[str] = mapped_column(String(100), index=True)
    prenom: Mapped[str] = mapped_column(String(100))

    # Infos optionnelles
    date_naissance: Mapped[Optional[dt_date]] = mapped_column(Date, nullable=True)
    nationalite: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)

    # Stats agrégées (calculées)
    matchs_joues: Mapped[int] = mapped_column(Integer, default=0)
    sets_joues: Mapped[int] = mapped_column(Integer, default=0)

    # Relations
    equipes: Mapped[List["EquipeDB"]] = relationship(
        secondary=joueur_equipe, back_populates="joueurs"
    )
    participations: Mapped[List["ParticipationMatchDB"]] = relationship(back_populates="joueur")

    __table_args__ = (
        Index("ix_joueurs_nom_prenom", "nom", "prenom"),
    )

    @property
    def nom_complet(self) -> str:
        return f"{self.nom} {self.prenom}"

    def __repr__(self) -> str:
        return f"<Joueur {self.nom} {self.prenom} ({self.licence})>"


# ============== Compétition ==============

class CompetitionDB(Base):
    """Compétition (championnat, coupe, etc.)."""
    __tablename__ = "competitions"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(20))  # "PMA", "1MA", etc.
    nom: Mapped[str] = mapped_column(String(200))

    # Caractéristiques
    genre: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    categorie: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    niveau: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    ligue: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)

    # Foreign keys
    saison_id: Mapped[Optional[int]] = mapped_column(ForeignKey("saisons.id"), nullable=True)

    # Relations
    saison: Mapped[Optional["SaisonDB"]] = relationship(back_populates="competitions")
    matchs: Mapped[List["MatchDB"]] = relationship(back_populates="competition")

    __table_args__ = (
        UniqueConstraint("code", "saison_id", name="uq_competition_code_saison"),
    )

    def __repr__(self) -> str:
        return f"<Competition {self.code} - {self.nom}>"


# ============== Match ==============

class MatchDB(Base):
    """Match de volleyball."""
    __tablename__ = "matchs"

    id: Mapped[int] = mapped_column(primary_key=True)
    code_match: Mapped[str] = mapped_column(String(30), index=True)  # "PMAA001"

    # Date et lieu
    date_match: Mapped[Optional[dt_date]] = mapped_column(Date, nullable=True)
    heure_match: Mapped[Optional[dt_time]] = mapped_column(Time, nullable=True)
    lieu: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    salle: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)

    # Journée
    journee: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)

    # Foreign keys
    competition_id: Mapped[Optional[int]] = mapped_column(ForeignKey("competitions.id"), nullable=True)
    saison_id: Mapped[Optional[int]] = mapped_column(ForeignKey("saisons.id"), nullable=True)
    equipe_a_id: Mapped[Optional[int]] = mapped_column(ForeignKey("equipes.id"), nullable=True)
    equipe_b_id: Mapped[Optional[int]] = mapped_column(ForeignKey("equipes.id"), nullable=True)
    vainqueur_id: Mapped[Optional[int]] = mapped_column(ForeignKey("equipes.id"), nullable=True)

    # Résultat
    vainqueur_nom: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    score_final: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)  # "3-1"
    sets_equipe_a: Mapped[int] = mapped_column(Integer, default=0)
    sets_equipe_b: Mapped[int] = mapped_column(Integer, default=0)
    duree_totale: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)

    # Remarques
    remarques: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Métadonnées
    source_pdf: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    parsed_at: Mapped[Optional[dt]] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[dt] = mapped_column(DateTime, default=dt.now)
    updated_at: Mapped[dt] = mapped_column(DateTime, default=dt.now, onupdate=dt.now)

    # Relations
    competition: Mapped[Optional["CompetitionDB"]] = relationship(back_populates="matchs")
    saison: Mapped[Optional["SaisonDB"]] = relationship(back_populates="matchs")
    equipe_a: Mapped[Optional["EquipeDB"]] = relationship(foreign_keys=[equipe_a_id])
    equipe_b: Mapped[Optional["EquipeDB"]] = relationship(foreign_keys=[equipe_b_id])
    vainqueur: Mapped[Optional["EquipeDB"]] = relationship(foreign_keys=[vainqueur_id])
    sets: Mapped[List["SetDB"]] = relationship(
        back_populates="match", cascade="all, delete-orphan", order_by="SetDB.numero"
    )
    arbitres: Mapped[List["ArbitreMatchDB"]] = relationship(
        back_populates="match", cascade="all, delete-orphan"
    )
    sanctions: Mapped[List["SanctionDB"]] = relationship(
        back_populates="match", cascade="all, delete-orphan"
    )
    participations: Mapped[List["ParticipationMatchDB"]] = relationship(
        back_populates="match", cascade="all, delete-orphan"
    )

    __table_args__ = (
        UniqueConstraint("code_match", "saison_id", name="uq_match_code_saison"),
        Index("ix_matchs_date", "date_match"),
    )

    @property
    def is_played(self) -> bool:
        return self.vainqueur_id is not None or self.sets_equipe_a > 0

    def __repr__(self) -> str:
        return f"<Match {self.code_match}>"


# ============== Set ==============

class SetDB(Base):
    """Set d'un match."""
    __tablename__ = "sets"

    id: Mapped[int] = mapped_column(primary_key=True)
    numero: Mapped[int] = mapped_column(Integer)  # 1 à 5

    # Foreign key
    match_id: Mapped[int] = mapped_column(ForeignKey("matchs.id", ondelete="CASCADE"))

    # Scores
    score_a: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    score_b: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    # Horaires (stockés en string pour simplicité)
    heure_debut: Mapped[Optional[str]] = mapped_column(String(8), nullable=True)  # "14:30:00"
    heure_fin: Mapped[Optional[str]] = mapped_column(String(8), nullable=True)
    duree_minutes: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    # Service initial
    service_initial: Mapped[Optional[str]] = mapped_column(String(1), nullable=True)

    # Formations et temps morts (JSON)
    formation_a: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    formation_b: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    timeouts_a: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    timeouts_b: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Relations
    match: Mapped["MatchDB"] = relationship(back_populates="sets")

    @property
    def vainqueur(self) -> Optional[str]:
        if self.score_a is not None and self.score_b is not None:
            return "A" if self.score_a > self.score_b else "B"
        return None

    def __repr__(self) -> str:
        return f"<Set {self.numero}: {self.score_a}-{self.score_b}>"


# ============== Arbitre ==============

class ArbitreDB(Base):
    """Arbitre officiel."""
    __tablename__ = "arbitres"

    id: Mapped[int] = mapped_column(primary_key=True)
    licence: Mapped[Optional[str]] = mapped_column(String(20), unique=True, nullable=True, index=True)
    nom: Mapped[str] = mapped_column(String(100), index=True)
    prenom: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    ligue: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    grade: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)

    # Relations
    matchs: Mapped[List["ArbitreMatchDB"]] = relationship(back_populates="arbitre")

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

    # Foreign keys
    arbitre_id: Mapped[int] = mapped_column(ForeignKey("arbitres.id", ondelete="CASCADE"))
    match_id: Mapped[int] = mapped_column(ForeignKey("matchs.id", ondelete="CASCADE"))

    # Rôle dans le match
    role: Mapped[str] = mapped_column(String(30))  # "1er", "2ème", "Marqueur"

    # Relations
    arbitre: Mapped["ArbitreDB"] = relationship(back_populates="matchs")
    match: Mapped["MatchDB"] = relationship(back_populates="arbitres")

    __table_args__ = (
        UniqueConstraint("arbitre_id", "match_id", "role", name="uq_arbitre_match_role"),
    )


# ============== Sanction ==============

class SanctionDB(Base):
    """Sanction donnée pendant un match."""
    __tablename__ = "sanctions"

    id: Mapped[int] = mapped_column(primary_key=True)

    # Foreign keys
    match_id: Mapped[int] = mapped_column(ForeignKey("matchs.id", ondelete="CASCADE"))
    joueur_id: Mapped[Optional[int]] = mapped_column(ForeignKey("joueurs.id"), nullable=True)

    # Détails
    type_sanction: Mapped[str] = mapped_column(String(1))  # A, P, E, D
    set_numero: Mapped[int] = mapped_column(Integer)
    equipe: Mapped[str] = mapped_column(String(1))  # A ou B
    joueur_numero: Mapped[Optional[str]] = mapped_column(String(5), nullable=True)
    score_a: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    score_b: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    # Relations
    match: Mapped["MatchDB"] = relationship(back_populates="sanctions")
    joueur: Mapped[Optional["JoueurDB"]] = relationship()

    def __repr__(self) -> str:
        return f"<Sanction {self.type_sanction} set {self.set_numero}>"


# ============== Participation Match ==============

class ParticipationMatchDB(Base):
    """Participation d'un joueur à un match."""
    __tablename__ = "participations_match"

    id: Mapped[int] = mapped_column(primary_key=True)

    # Foreign keys
    match_id: Mapped[int] = mapped_column(ForeignKey("matchs.id", ondelete="CASCADE"))
    joueur_id: Mapped[int] = mapped_column(ForeignKey("joueurs.id", ondelete="CASCADE"))
    equipe_id: Mapped[int] = mapped_column(ForeignKey("equipes.id", ondelete="CASCADE"))

    # Détails
    numero_maillot: Mapped[Optional[str]] = mapped_column(String(5), nullable=True)
    est_capitaine: Mapped[bool] = mapped_column(Boolean, default=False)
    est_libero: Mapped[bool] = mapped_column(Boolean, default=False)
    est_titulaire: Mapped[bool] = mapped_column(Boolean, default=True)

    # Relations
    match: Mapped["MatchDB"] = relationship(back_populates="participations")
    joueur: Mapped["JoueurDB"] = relationship(back_populates="participations")
    equipe: Mapped["EquipeDB"] = relationship(back_populates="participations")

    __table_args__ = (
        UniqueConstraint("match_id", "joueur_id", name="uq_participation"),
        Index("ix_participation_match_joueur", "match_id", "joueur_id"),
    )

    def __repr__(self) -> str:
        return f"<Participation joueur={self.joueur_id} match={self.match_id}>"
