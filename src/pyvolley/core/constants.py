"""
Constantes universelles et énumérations métier pour PyVolley.

Centralise les énumérations transversales (genres, catégories, niveaux, sanctions, arbitres, rôles joueurs),
ainsi que leurs libellés humains et palettes de couleurs utilisées dans l'analyse, la CLI, l'API et le web.
"""

from __future__ import annotations

from enum import Enum


# ── Énumérations du domaine ─────────────────────────────────────────

class Genre(str, Enum):
    """Genre de la compétition ou de l'équipe."""
    MASCULIN = "MASCULIN"
    FEMININ = "FEMININ"
    MIXTE = "MIXTE"


class Categorie(str, Enum):
    """Catégorie d'âge FFVB."""
    SENIOR = "SENIOR"
    M21 = "M21"
    M20 = "M20"
    M18 = "M18"
    M17 = "M17"
    M15 = "M15"
    M14 = "M14"
    M13 = "M13"
    M11 = "M11"
    M9 = "M9"
    JEUNES = "JEUNES"
    VETERAN = "VETERAN"


class Niveau(str, Enum):
    """Niveau d'échelon de compétition."""
    PRO = "PRO"
    ELITE = "ELITE"
    NATIONALE = "NATIONALE"
    PRE_NATIONALE = "PRE_NATIONALE"
    REGIONALE = "REGIONALE"
    PRE_REGIONALE = "PRE_REGIONALE"
    DEPARTEMENTALE = "DEPARTEMENTALE"
    COUPE_DE_FRANCE = "COUPE_DE_FRANCE"
    LOISIR = "LOISIR"


class TypeSanction(str, Enum):
    """Type de sanction sportive FFVB."""
    AVERTISSEMENT = "A"  # Carton jaune
    PENALITE = "P"       # Carton rouge = point adverse
    EXPULSION = "E"      # Exclusion du set
    DISQUALIFICATION = "D"  # Exclusion du match


class RoleArbitre(str, Enum):
    """Rôle de l'arbitre sur une feuille de match."""
    PREMIER = "1er"
    SECOND = "2ème"
    MARQUEUR = "Marqueur"
    MARQUEUR_ASSISTANT = "Marqueur assistant"
    RESPONSABLE_SALLE = "Responsable de salle"
    JUGE_LIGNE = "Juge de ligne"


class RoleJoueur(str, Enum):
    """Rôles officiels et tactiques d'un joueur de volleyball."""
    PASSEUR = "PASSEUR"
    POINTU = "POINTU"
    CENTRAL = "CENTRAL"
    RECEPTIONNEUR_ATTAQUANT = "RECEPTIONNEUR_ATTAQUANT"
    LIBERO = "LIBERO"
    POLYVALENT = "POLYVALENT"
    INDETERMINE = "INDETERMINE"


# ── Constantes textuelles pour rétro-compatibilité ──────────────────
ROLE_SETTER = RoleJoueur.PASSEUR.value
ROLE_OPPOSITE = RoleJoueur.POINTU.value
ROLE_MIDDLE = RoleJoueur.CENTRAL.value
ROLE_OUTSIDE = RoleJoueur.RECEPTIONNEUR_ATTAQUANT.value
ROLE_LIBERO = RoleJoueur.LIBERO.value
ROLE_MULTI = RoleJoueur.POLYVALENT.value
ROLE_UNKNOWN = RoleJoueur.INDETERMINE.value

# ── Groupements de rôles ─────────────────────────────────────────────
# Les 5 postes spécifiques de rotation 6x6
ALL_SPECIFIC_ROLES: tuple[str, ...] = (
    ROLE_SETTER,
    ROLE_OPPOSITE,
    ROLE_MIDDLE,
    ROLE_OUTSIDE,
    ROLE_LIBERO,
)

# Tous les rôles possibles incluant polyvalents et indéterminés
ALL_ROLES: tuple[str, ...] = (
    ROLE_SETTER,
    ROLE_OPPOSITE,
    ROLE_MIDDLE,
    ROLE_OUTSIDE,
    ROLE_LIBERO,
    ROLE_MULTI,
    ROLE_UNKNOWN,
)

# ── Libellés humains ────────────────────────────────────────────────
ROLE_LABELS: dict[str, str] = {
    ROLE_SETTER: "Passeur",
    ROLE_OPPOSITE: "Pointu",
    ROLE_MIDDLE: "Central",
    ROLE_OUTSIDE: "Réceptionneur-Attaquant",
    ROLE_LIBERO: "Libéro",
    ROLE_MULTI: "Polyvalent",
    ROLE_UNKNOWN: "Indéterminé",
}

GENRE_LABELS: dict[str, str] = {
    Genre.MASCULIN.value: "Masculin",
    Genre.FEMININ.value: "Féminin",
    Genre.MIXTE.value: "Mixte",
}

SANCTION_LABELS: dict[str, str] = {
    TypeSanction.AVERTISSEMENT.value: "Avertissement",
    TypeSanction.PENALITE.value: "Pénalité",
    TypeSanction.EXPULSION.value: "Expulsion",
    TypeSanction.DISQUALIFICATION.value: "Disqualification",
}

ROLE_ARBITRE_LABELS: dict[str, str] = {
    RoleArbitre.PREMIER.value: "1er Arbitre",
    RoleArbitre.SECOND.value: "2ème Arbitre",
    RoleArbitre.MARQUEUR.value: "Marqueur",
    RoleArbitre.MARQUEUR_ASSISTANT.value: "Marqueur Assistant",
    RoleArbitre.RESPONSABLE_SALLE.value: "Responsable de Salle",
    RoleArbitre.JUGE_LIGNE.value: "Juge de Ligne",
}

# ── Couleurs associées (dark mode & charts) ─────────────────────────
ROLE_COLORS: dict[str, str] = {
    ROLE_SETTER: "#3b82f6",     # Bleu électrique
    ROLE_OPPOSITE: "#f59e0b",   # Ambre / Or
    ROLE_MIDDLE: "#10b981",     # Émeraude
    ROLE_OUTSIDE: "#8b5cf6",    # Violet
    ROLE_LIBERO: "#ef4444",     # Rouge
    ROLE_MULTI: "#06b6d4",      # Cyan
    ROLE_UNKNOWN: "#6b7280",    # Gris neutre
}


def get_role_label(role_code: str | None, default: str = "Indéterminé") -> str:
    """Retourne le libellé français formaté d'un rôle joueur."""
    if not role_code:
        return default
    return ROLE_LABELS.get(role_code.upper(), role_code.replace("_", " ").title())

