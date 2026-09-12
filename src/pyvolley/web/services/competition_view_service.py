"""
Service de vue pour la présentation hiérarchique et multi-niveaux des compétitions.

Structure les compétitions pour une saison donnée :
1. Organisation par échelon territorial (National, Régional, Départemental, Coupe de France, Loisir).
2. Tri et regroupement par niveau sportif (Elite, N2, N3, Prénat, R1, R2, D1...).
3. Calcul des métriques globales et filtrage dynamique.
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from pyvolley.shared.niveau import (
    ECHELON_METADATA,
    classify_level,
    resolve_competition_echelon,
    niveau_sort_rank,
)


@dataclass
class CompetitionCardDTO:
    """Modèle de données enrichi pour une carte de compétition."""

    id: int
    nom: str
    code_competition: Optional[str]
    genre: Optional[str]
    categorie: Optional[str]
    niveau: Optional[str]
    division: Optional[str]
    saison_id: Optional[int]
    saison_code: Optional[str]
    entite_id: Optional[int]
    entite_nom: Optional[str]
    entite_code: Optional[str]
    entite_type: Optional[str]

    # Classification hiérarchique
    echelon_key: str
    echelon_label: str
    level_label: str
    level_css: str
    level_rank: int
    is_youth: bool

    # Compteurs
    poules_count: int = 0
    matchs_count: int = 0
    equipes_count: int = 0

    @property
    def url(self) -> str:
        code = self.code_competition or str(self.id)
        return f"/competitions/{code}"


@dataclass
class LevelGroupDTO:
    """Groupe de compétitions d'un même niveau au sein d'un échelon."""

    level_label: str
    level_css: str
    level_rank: int
    competitions: List[CompetitionCardDTO] = field(default_factory=list)
    total_matches: int = 0
    total_poules: int = 0

    @property
    def count(self) -> int:
        return len(self.competitions)


@dataclass
class EchelonGroupDTO:
    """Groupe territorial majeur (National, Régional, Départemental, etc.)."""

    key: str
    label: str
    short_label: str
    icon: str
    badge_css: str
    description: str
    order: int
    level_groups: List[LevelGroupDTO] = field(default_factory=list)
    competitions: List[CompetitionCardDTO] = field(default_factory=list)
    total_competitions: int = 0
    total_matches: int = 0
    total_poules: int = 0


@dataclass
class CompetitionPresentationPageDTO:
    """Structure complète pour le rendu du template des compétitions."""

    current_saison_id: Optional[int]
    current_saison_code: Optional[str]
    saisons: List[Dict[str, Any]]
    echelons: List[EchelonGroupDTO]
    all_competitions: List[CompetitionCardDTO]

    # KPIs globaux
    total_competitions: int
    total_national: int
    total_regional: int
    total_departemental: int
    total_coupes: int
    total_loisir: int
    total_matches: int
    total_poules: int

    # Filtres & état UI
    active_echelon: Optional[str] = None
    active_genre: Optional[str] = None
    active_categorie: Optional[str] = None
    active_q: Optional[str] = None
    active_view: str = "grid"  # "grid" ou "table"
    genres: List[str] = field(default_factory=list)
    categories: List[str] = field(default_factory=list)
    filter_applied: bool = False


class CompetitionViewService:
    """Service d'agrégation et mise en forme hiérarchique des compétitions."""

    @staticmethod
    def _to_card_dto(comp: Any) -> CompetitionCardDTO:
        if isinstance(comp, dict):
            c_id = comp.get("id", 0)
            c_nom = comp.get("nom", "")
            c_code = comp.get("code_competition", None)
            c_genre = comp.get("genre", None)
            c_cat = comp.get("categorie", None)
            c_niv = comp.get("niveau", None)
            c_div = comp.get("division", None)
        else:
            c_id = getattr(comp, "id", 0)
            c_nom = getattr(comp, "nom", "")
            c_code = getattr(comp, "code_competition", None)
            c_genre = getattr(comp, "genre", None)
            c_cat = getattr(comp, "categorie", None)
            c_niv = getattr(comp, "niveau", None)
            c_div = getattr(comp, "division", None)


        # Saison
        saison_obj = getattr(comp, "saison", None)
        if saison_obj:
            s_id = getattr(saison_obj, "id", None)
            s_code = getattr(saison_obj, "code", None)
        else:
            s_id = comp.get("saison_id") if isinstance(comp, dict) else getattr(comp, "saison_id", None)
            s_code = comp.get("saison_code") if isinstance(comp, dict) else None

        # Entité organisatrice
        entite_obj = getattr(comp, "entite", None)
        if entite_obj:
            e_id = getattr(entite_obj, "id", None)
            e_nom = getattr(entite_obj, "nom", None)
            e_code = getattr(entite_obj, "code", None)
            e_type = getattr(entite_obj, "type", None)
        elif isinstance(comp, dict):
            e_id = comp.get("entite_id")
            e_nom = comp.get("entite_nom")
            e_code = comp.get("entite_code")
            e_type = comp.get("entite_type")
        else:
            e_id = getattr(comp, "entite_id", None)
            e_nom = None
            e_code = None
            e_type = None

        # Classification du niveau
        classification = classify_level(
            competition_name=c_nom,
            niveau=c_niv,
            categorie=c_cat,
            division=c_div,
        )

        # Résolution de l'échelon territorial
        ech_key = resolve_competition_echelon(
            nom=c_nom,
            niveau=c_niv,
            categorie=c_cat,
            division=c_div,
            entite_type=e_type,
            code_competition=c_code,
        )
        ech_meta = ECHELON_METADATA.get(ech_key, ECHELON_METADATA["regional"])

        # Comptages des poules et matchs
        poules_count = 0
        matchs_count = 0
        equipes_count = 0

        if hasattr(comp, "poules") and comp.poules is not None:
            try:
                poules_count = len(comp.poules)
            except Exception:
                poules_count = 0
        elif isinstance(comp, dict) and "poules_count" in comp:
            poules_count = comp["poules_count"]

        if hasattr(comp, "matchs") and comp.matchs is not None:
            try:
                matchs_count = len(comp.matchs)
            except Exception:
                matchs_count = 0
        elif isinstance(comp, dict) and "matchs_count" in comp:
            matchs_count = comp["matchs_count"]

        if hasattr(comp, "equipes") and comp.equipes is not None:
            try:
                equipes_count = len(comp.equipes)
            except Exception:
                equipes_count = 0
        elif isinstance(comp, dict) and "equipes_count" in comp:
            equipes_count = comp["equipes_count"]

        return CompetitionCardDTO(
            id=c_id,
            nom=c_nom,
            code_competition=c_code,
            genre=c_genre,
            categorie=c_cat,
            niveau=c_niv,
            division=c_div,
            saison_id=s_id,
            saison_code=s_code,
            entite_id=e_id,
            entite_nom=e_nom,
            entite_code=e_code,
            entite_type=e_type,
            echelon_key=ech_key,
            echelon_label=ech_meta["label"],
            level_label=classification.label,
            level_css=classification.css_class,
            level_rank=classification.rank,
            is_youth=classification.is_youth,
            poules_count=poules_count,
            matchs_count=matchs_count,
            equipes_count=equipes_count,
        )

    @classmethod
    def prepare_competitions_page(
        cls,
        competitions: List[Any],
        saisons: List[Any],
        current_saison_id: Optional[int] = None,
        active_echelon: Optional[str] = None,
        active_genre: Optional[str] = None,
        active_categorie: Optional[str] = None,
        active_q: Optional[str] = None,
        active_view: str = "grid",
    ) -> CompetitionPresentationPageDTO:
        """Structure les données pour la page web de présentation des compétitions."""
        # 1. Conversion de tous les éléments en DTO
        all_dtos = [cls._to_card_dto(c) for c in competitions]

        # 2. Collecte des options distinctes
        distinct_genres = sorted({c.genre for c in all_dtos if c.genre})
        distinct_cats = sorted({c.categorie for c in all_dtos if c.categorie})

        # 3. Calcul des KPIs globaux avant filtrage UI local
        total_comps = len(all_dtos)
        count_national = sum(1 for c in all_dtos if c.echelon_key == "national")
        count_regional = sum(1 for c in all_dtos if c.echelon_key == "regional")
        count_departemental = sum(1 for c in all_dtos if c.echelon_key == "departemental")
        count_coupes = sum(1 for c in all_dtos if c.echelon_key == "coupe_de_france")
        count_loisir = sum(1 for c in all_dtos if c.echelon_key == "loisir")
        total_matches = sum(c.matchs_count for c in all_dtos)
        total_poules = sum(c.poules_count for c in all_dtos)

        # 4. Filtrage dynamique
        filtered_dtos = all_dtos
        filter_applied = bool(active_echelon or active_genre or active_categorie or active_q)

        if active_echelon and active_echelon != "all":
            filtered_dtos = [c for c in filtered_dtos if c.echelon_key == active_echelon]
        if active_genre:
            filtered_dtos = [c for c in filtered_dtos if (c.genre or "").upper() == active_genre.upper()]
        if active_categorie:
            filtered_dtos = [c for c in filtered_dtos if (c.categorie or "").upper() == active_categorie.upper()]
        if active_q:
            q_lower = active_q.strip().lower()
            filtered_dtos = [
                c for c in filtered_dtos
                if q_lower in c.nom.lower()
                or (c.code_competition and q_lower in c.code_competition.lower())
                or (c.entite_nom and q_lower in c.entite_nom.lower())
                or (c.level_label and q_lower in c.level_label.lower())
            ]

        # 5. Tri des compétitions : niveau décroissant (Elite > N2 > N3...), puis seniors avant jeunes, puis genre, puis nom
        genre_order = {"MASCULIN": 1, "FEMININ": 2, "MIXTE": 3}

        def competition_sort_key(c: CompetitionCardDTO):
            return (
                -c.level_rank,                  # Niveau plus élevé en premier
                1 if c.is_youth else 0,         # Seniors d'abord
                genre_order.get(c.genre or "", 9),
                c.nom.upper(),
            )

        # 6. Regroupement par Échelon
        echelon_buckets: Dict[str, List[CompetitionCardDTO]] = defaultdict(list)
        for c in filtered_dtos:
            echelon_buckets[c.echelon_key].append(c)

        # Construction des EchelonGroupDTO
        echelon_dtos: List[EchelonGroupDTO] = []
        for ech_key, ech_meta in sorted(ECHELON_METADATA.items(), key=lambda item: item[1]["order"]):
            comps_in_echelon = echelon_buckets.get(ech_key, [])
            if not comps_in_echelon and active_echelon != ech_key and not filter_applied:
                continue

            # Tri des compétitions de cet échelon
            comps_in_echelon.sort(key=competition_sort_key)

            # Regroupement par niveau au sein de cet échelon
            level_buckets: Dict[str, List[CompetitionCardDTO]] = defaultdict(list)
            for c in comps_in_echelon:
                level_buckets[c.level_label].append(c)

            level_groups: List[LevelGroupDTO] = []
            for lvl_label, lvl_comps in level_buckets.items():
                if not lvl_comps:
                    continue
                first = lvl_comps[0]
                level_groups.append(
                    LevelGroupDTO(
                        level_label=lvl_label,
                        level_css=first.level_css,
                        level_rank=first.level_rank,
                        competitions=lvl_comps,
                        total_matches=sum(x.matchs_count for x in lvl_comps),
                        total_poules=sum(x.poules_count for x in lvl_comps),
                    )
                )

            # Tri des groupes de niveau : rank décroissant (Elite -> N2 -> N3...)
            level_groups.sort(key=lambda g: (-g.level_rank, g.level_label))

            echelon_dtos.append(
                EchelonGroupDTO(
                    key=ech_key,
                    label=ech_meta["label"],
                    short_label=ech_meta["short_label"],
                    icon=ech_meta["icon"],
                    badge_css=ech_meta["badge_css"],
                    description=ech_meta["description"],
                    order=ech_meta["order"],
                    level_groups=level_groups,
                    competitions=comps_in_echelon,
                    total_competitions=len(comps_in_echelon),
                    total_matches=sum(x.matchs_count for x in comps_in_echelon),
                    total_poules=sum(x.poules_count for x in comps_in_echelon),
                )
            )

        # 7. Saisons formatées pour sélecteur
        saison_list = []
        current_saison_code = None
        for s in saisons:
            s_id = getattr(s, "id", None) or s.get("id")
            s_code = getattr(s, "code", None) or s.get("code")
            is_active = (s_id == current_saison_id)
            if is_active:
                current_saison_code = s_code
            saison_list.append({
                "id": s_id,
                "code": s_code,
                "is_active": is_active,
            })

        return CompetitionPresentationPageDTO(
            current_saison_id=current_saison_id,
            current_saison_code=current_saison_code,
            saisons=saison_list,
            echelons=echelon_dtos,
            all_competitions=filtered_dtos,
            total_competitions=total_comps,
            total_national=count_national,
            total_regional=count_regional,
            total_departemental=count_departemental,
            total_coupes=count_coupes,
            total_loisir=count_loisir,
            total_matches=total_matches,
            total_poules=total_poules,
            active_echelon=active_echelon,
            active_genre=active_genre,
            active_categorie=active_categorie,
            active_q=active_q,
            active_view=active_view,
            genres=distinct_genres,
            categories=distinct_cats,
            filter_applied=filter_applied,
        )
