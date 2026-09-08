"""
Configuration et modèles de géométrie de layout pour les parsers FFVB.

Définit des zones de recherche géométriques (ROIs) extrêmement précises et déterministes
correspondant aux emplacements physiques réels sur la feuille de match A4 Paysage (841.89 x 595.28 pt).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional, Dict, List, Any


@dataclass
class LayoutRegion:
    """Représente une zone géométrique rectangulaire sur la feuille PDF (en points A4 paysage)."""
    name: str
    x0: float
    y0: float
    x1: float
    y1: float
    description: str = ""
    color: str = "#3B82F6"  # Couleur Hex pour l'overlay visualisateur GUI

    @property
    def width(self) -> float:
        return max(0.0, self.x1 - self.x0)

    @property
    def height(self) -> float:
        return max(0.0, self.y1 - self.y0)

    def contains_point(self, x: float, y: float) -> bool:
        return self.x0 <= x <= self.x1 and self.y0 <= y <= self.y1

    def contains_bbox(self, x0: float, y0: float, x1: float, y1: float) -> bool:
        cx = (x0 + x1) / 2.0
        cy = (y0 + y1) / 2.0
        return self.x0 <= cx <= self.x1 and self.y0 <= cy <= self.y1

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> LayoutRegion:
        return cls(
            name=data["name"],
            x0=float(data["x0"]),
            y0=float(data["y0"]),
            x1=float(data["x1"]),
            y1=float(data["y1"]),
            description=data.get("description", ""),
            color=data.get("color", "#3B82F6"),
        )


@dataclass
class ParserLayoutConfig:
    """Configuration complète de layout et de géométrie d'extraction FFVB."""

    name: str = "Standard FFVB Précis"
    version: str = "3.0"
    page_width: float = 841.89
    page_height: float = 595.28

    # Zones de recherche rectangulaires (ROIs) précises
    bboxes: Dict[str, LayoutRegion] = field(default_factory=dict)

    # Bornes de colonnes (points X)
    main_cols: List[float] = field(default_factory=lambda: [
        10.0, 25.0, 45.0, 65.0, 85.0, 105.0, 125.0, 145.0, 165.0, 185.0,
        205.0, 225.0, 245.0, 265.0, 285.0, 305.0, 325.0, 345.0, 365.0, 385.0, 410.0
    ])
    sec_cols: List[float] = field(default_factory=lambda: [
        405.0, 420.0, 440.0, 460.0, 480.0, 500.0, 520.0, 540.0, 560.0, 580.0,
        600.0, 620.0, 640.0, 660.0, 680.0, 700.0, 720.0, 740.0, 755.0, 775.0
    ])
    res_cols: List[float] = field(default_factory=lambda: [
        415.0, 430.0, 445.0, 460.0, 475.0, 490.0, 505.0, 520.0, 535.0, 550.0, 570.0
    ])
    sig_cols: List[float] = field(default_factory=lambda: [
        570.0, 700.0, 835.0
    ])

    # Paramètres d'alignement et seuils
    x_split: float = 700.0
    y_tolerance: float = 3.5

    def __post_init__(self):
        if not self.bboxes:
            self.bboxes = self._default_regions()

    @staticmethod
    def _default_regions() -> Dict[str, LayoutRegion]:
        """Zones géométriques de recherche réelles extraites de parser-preset-update-new-new.json."""
        return {
            "header/organisateur": LayoutRegion(name="header/organisateur", x0=10.0, y0=55.0, x1=115.0, y1=72.0, description="Organisateur (Ligue / Comité / Compétitions)", color="#10B981"),
            "header/competition": LayoutRegion(name="header/competition", x0=114.4, y0=25.0, x1=682.0, y1=39.4, description="Intitulé de la Compétition & Poule", color="#059669"),
            "header/match_code": LayoutRegion(name="header/match_code", x0=743.0, y0=25.0, x1=782.0, y1=39.1, description="Code Match (Valeur exacte)", color="#3B82F6"),
            "header/journee": LayoutRegion(name="header/journee", x0=809.0, y0=25.0, x1=835.0, y1=41.0, description="Numéro de Journée (Valeur exacte)", color="#6366F1"),
            "header/ville": LayoutRegion(name="header/ville", x0=130.0, y0=36.5, x1=400.0, y1=46.2, description="Nom de la Ville (Valeur exacte)", color="#8B5CF6"),
            "header/date": LayoutRegion(name="header/date", x0=680.0, y0=37.0, x1=825.0, y1=51.0, description="Date du Match & Heure", color="#EC4899"),
            "header/salle": LayoutRegion(name="header/salle", x0=132.0, y0=46.2, x1=400.0, y1=56.0, description="Nom de la Salle / Gymnase (Valeur exacte)", color="#F43F5E"),
            "header/division_categorie": LayoutRegion(name="header/division_categorie", x0=362.4, y0=44.6, x1=532.4, y1=54.4, description="Catégorie & Genre (Valeur exacte)", color="#D97706"),
            "header/equipes/gauche": LayoutRegion(name="header/equipes/gauche", x0=115.0, y0=55.0, x1=420.0, y1=74.0, description="Nom Équipe Côté Gauche (Valeur exacte)", color="#06B6D4"),
            "header/equipes/droite": LayoutRegion(name="header/equipes/droite", x0=420.5, y0=54.1, x1=720.5, y1=73.1, description="Nom Équipe Côté Droit (Valeur exacte)", color="#0284C7"),
            "equipes/gauche/joueurs": LayoutRegion(name="equipes/gauche/joueurs", x0=574.1, y0=282.5, x1=701.8, y1=403.6, description="Joueurs Équipe Gauche (N° Maillot, Nom, Prénom, Licence, Capitaine)", color="#06B6D4"),
            "equipes/gauche/liberos": LayoutRegion(name="equipes/gauche/liberos", x0=575.0, y0=412.0, x1=703.0, y1=431.0, description="Libéros Équipe Gauche (Valeurs uniquement)", color="#14B8A6"),
            "equipes/gauche/officiels": LayoutRegion(name="equipes/gauche/officiels", x0=575.0, y0=440.8, x1=703.0, y1=474.2, description="Staff & Officiels Équipe Gauche (Valeurs uniquement)", color="#64748B"),
            "equipes/droite/joueurs": LayoutRegion(name="equipes/droite/joueurs", x0=703.2, y0=282.2, x1=830.6, y1=403.6, description="Joueurs Équipe Droite (N° Maillot, Nom, Prénom, Licence, Capitaine)", color="#0284C7"),
            "equipes/droite/liberos": LayoutRegion(name="equipes/droite/liberos", x0=702.0, y0=412.0, x1=835.0, y1=431.0, description="Libéros Équipe Droite (Valeurs uniquement)", color="#0D9488"),
            "equipes/droite/officiels": LayoutRegion(name="equipes/droite/officiels", x0=702.0, y0=440.0, x1=831.4, y1=476.2, description="Staff & Officiels Équipe Droite (Valeurs uniquement)", color="#475569"),
            "sanctions/demandes_non_fondees": LayoutRegion(name="sanctions/demandes_non_fondees", x0=70.8, y0=388.0, x1=127.8, y1=514.6, description="Demandes Non Fondées", color="#D97706"),
            "sanctions/cartons": LayoutRegion(name="sanctions/cartons", x0=14.6, y0=387.6, x1=70.8, y1=515.8, description="Sanctions & Cartons", color="#F59E0B"),
            "arbitres": LayoutRegion(name="arbitres", x0=129.8, y0=440.8, x1=306.4, y1=501.0, description="Corps Arbitral (1er, 2ème, Marqueur, Marqueur Adjoint, Responsable de Salle, Juges)", color="#EF4444"),
            "resultats": LayoutRegion(name="resultats", x0=425.0, y0=450.4, x1=561.8, y1=546.6, description="Tableau Récapitulatif des Résultats (Sets 1 à 5, Durée, Vainqueur, Score)", color="#10B981"),
            "remarques": LayoutRegion(name="remarques", x0=131.2, y0=358.3, x1=569.2, y1=421.9, description="Remarques, Observations & Réclamations (Avant/Après match)", color="#F97316"),
            "sets/set1/debut": LayoutRegion(name="sets/set1/debut", x0=257.9, y0=75.7, x1=274.3, y1=85.2, description="Set 1 - Heure de Début", color="#6366F1"),
            "sets/set1/fin": LayoutRegion(name="sets/set1/fin", x0=413.5, y0=75.0, x1=430.0, y1=85.2, description="Set 1 - Heure de Fin", color="#818CF8"),
            "sets/set1/equipe_a/pos1": LayoutRegion(name="sets/set1/equipe_a/pos1", x0=127.4, y0=95.7, x1=147.1, y1=130.8, description="Set 1 - Équipe A - Position I (Titulaire, Remplaçant, Score)", color="#8B5CF6"),
            "sets/set1/equipe_a/pos2": LayoutRegion(name="sets/set1/equipe_a/pos2", x0=147.8, y0=96.8, x1=166.4, y1=129.8, description="Set 1 - Équipe A - Position II (Titulaire, Remplaçant, Score)", color="#9333EA"),
            "sets/set1/equipe_a/pos3": LayoutRegion(name="sets/set1/equipe_a/pos3", x0=166.7, y0=96.8, x1=186.4, y1=129.8, description="Set 1 - Équipe A - Position III (Titulaire, Remplaçant, Score)", color="#A855F7"),
            "sets/set1/equipe_a/pos4": LayoutRegion(name="sets/set1/equipe_a/pos4", x0=186.0, y0=96.8, x1=206.4, y1=129.8, description="Set 1 - Équipe A - Position IV (Titulaire, Remplaçant, Score)", color="#C084FC"),
            "sets/set1/equipe_a/pos5": LayoutRegion(name="sets/set1/equipe_a/pos5", x0=207.1, y0=96.4, x1=225.6, y1=129.8, description="Set 1 - Équipe A - Position V (Titulaire, Remplaçant, Score)", color="#D8B4FE"),
            "sets/set1/equipe_a/pos6": LayoutRegion(name="sets/set1/equipe_a/pos6", x0=226.7, y0=95.3, x1=245.6, y1=129.8, description="Set 1 - Équipe A - Position VI (Titulaire, Remplaçant, Score)", color="#E9D5FF"),
            "sets/set1/equipe_a/services": LayoutRegion(name="sets/set1/equipe_a/services", x0=127.1, y0=130.5, x1=245.6, y1=170.8, description="Set 1 - Équipe A - Rotations de services", color="#D8B4FE"),
            "sets/set1/equipe_a/timeouts": LayoutRegion(name="sets/set1/equipe_a/timeouts", x0=245.9, y0=147.4, x1=283.0, y1=163.7, description="Set 1 - Équipe A - Temps Morts", color="#E9D5FF"),
            "sets/set1/equipe_b/pos1": LayoutRegion(name="sets/set1/equipe_b/pos1", x0=283.1, y0=96.1, x1=302.8, y1=129.8, description="Set 1 - Équipe B - Position I (Titulaire, Remplaçant, Score)", color="#7C3AED"),
            "sets/set1/equipe_b/pos2": LayoutRegion(name="sets/set1/equipe_b/pos2", x0=303.5, y0=97.1, x1=323.1, y1=130.1, description="Set 1 - Équipe B - Position II (Titulaire, Remplaçant, Score)", color="#8B5CF6"),
            "sets/set1/equipe_b/pos3": LayoutRegion(name="sets/set1/equipe_b/pos3", x0=322.8, y0=96.1, x1=342.4, y1=130.5, description="Set 1 - Équipe B - Position III (Titulaire, Remplaçant, Score)", color="#9333EA"),
            "sets/set1/equipe_b/pos4": LayoutRegion(name="sets/set1/equipe_b/pos4", x0=342.4, y0=96.1, x1=362.1, y1=130.5, description="Set 1 - Équipe B - Position IV (Titulaire, Remplaçant, Score)", color="#A855F7"),
            "sets/set1/equipe_b/pos5": LayoutRegion(name="sets/set1/equipe_b/pos5", x0=362.4, y0=96.1, x1=382.1, y1=129.8, description="Set 1 - Équipe B - Position V (Titulaire, Remplaçant, Score)", color="#C084FC"),
            "sets/set1/equipe_b/pos6": LayoutRegion(name="sets/set1/equipe_b/pos6", x0=382.1, y0=95.7, x1=402.4, y1=129.8, description="Set 1 - Équipe B - Position VI (Titulaire, Remplaçant, Score)", color="#D8B4FE"),
            "sets/set1/equipe_b/services": LayoutRegion(name="sets/set1/equipe_b/services", x0=283.1, y0=130.8, x1=401.7, y1=169.4, description="Set 1 - Équipe B - Rotations de services", color="#C084FC"),
            "sets/set1/equipe_b/timeouts": LayoutRegion(name="sets/set1/equipe_b/timeouts", x0=402.5, y0=147.4, x1=438.9, y1=164.4, description="Set 1 - Équipe B - Temps Morts", color="#DDD6FE"),
            "sets/set2/debut": LayoutRegion(name="sets/set2/debut", x0=592.9, y0=75.7, x1=609.3, y1=85.2, description="Set 2 - Heure de Début", color="#6366F1"),
            "sets/set2/fin": LayoutRegion(name="sets/set2/fin", x0=748.5, y0=75.0, x1=765.0, y1=85.2, description="Set 2 - Heure de Fin", color="#818CF8"),
            "sets/set2/equipe_b/pos1": LayoutRegion(name="sets/set2/equipe_b/pos1", x0=462.4, y0=95.7, x1=482.1, y1=130.8, description="Set 2 - Équipe A - Position I (Titulaire, Remplaçant, Score)", color="#8B5CF6"),
            "sets/set2/equipe_b/pos2": LayoutRegion(name="sets/set2/equipe_b/pos2", x0=482.8, y0=96.8, x1=501.4, y1=129.8, description="Set 2 - Équipe A - Position II (Titulaire, Remplaçant, Score)", color="#9333EA"),
            "sets/set2/equipe_b/pos3": LayoutRegion(name="sets/set2/equipe_b/pos3", x0=501.7, y0=96.8, x1=521.4, y1=129.8, description="Set 2 - Équipe A - Position III (Titulaire, Remplaçant, Score)", color="#A855F7"),
            "sets/set2/equipe_b/pos4": LayoutRegion(name="sets/set2/equipe_b/pos4", x0=521.0, y0=96.8, x1=541.4, y1=129.8, description="Set 2 - Équipe A - Position IV (Titulaire, Remplaçant, Score)", color="#C084FC"),
            "sets/set2/equipe_b/pos5": LayoutRegion(name="sets/set2/equipe_b/pos5", x0=542.1, y0=96.4, x1=560.6, y1=129.8, description="Set 2 - Équipe A - Position V (Titulaire, Remplaçant, Score)", color="#D8B4FE"),
            "sets/set2/equipe_b/pos6": LayoutRegion(name="sets/set2/equipe_b/pos6", x0=561.7, y0=95.3, x1=580.6, y1=129.8, description="Set 2 - Équipe A - Position VI (Titulaire, Remplaçant, Score)", color="#E9D5FF"),
            "sets/set2/equipe_b/services": LayoutRegion(name="sets/set2/equipe_b/services", x0=462.1, y0=130.5, x1=580.6, y1=170.8, description="Set 2 - Équipe A - Rotations de services", color="#D8B4FE"),
            "sets/set2/equipe_b/timeouts": LayoutRegion(name="sets/set2/equipe_b/timeouts", x0=580.9, y0=147.4, x1=618.0, y1=163.7, description="Set 2 - Équipe A - Temps Morts", color="#E9D5FF"),
            "sets/set2/equipe_a/pos1": LayoutRegion(name="sets/set2/equipe_a/pos1", x0=618.1, y0=96.1, x1=637.8, y1=129.8, description="Set 2 - Équipe B - Position I (Titulaire, Remplaçant, Score)", color="#7C3AED"),
            "sets/set2/equipe_a/pos2": LayoutRegion(name="sets/set2/equipe_a/pos2", x0=638.5, y0=97.1, x1=658.1, y1=130.1, description="Set 2 - Équipe B - Position II (Titulaire, Remplaçant, Score)", color="#8B5CF6"),
            "sets/set2/equipe_a/pos3": LayoutRegion(name="sets/set2/equipe_a/pos3", x0=657.8, y0=96.1, x1=677.4, y1=130.5, description="Set 2 - Équipe B - Position III (Titulaire, Remplaçant, Score)", color="#9333EA"),
            "sets/set2/equipe_a/pos4": LayoutRegion(name="sets/set2/equipe_a/pos4", x0=677.4, y0=96.1, x1=697.1, y1=130.5, description="Set 2 - Équipe B - Position IV (Titulaire, Remplaçant, Score)", color="#A855F7"),
            "sets/set2/equipe_a/pos5": LayoutRegion(name="sets/set2/equipe_a/pos5", x0=697.4, y0=96.1, x1=717.1, y1=129.8, description="Set 2 - Équipe B - Position V (Titulaire, Remplaçant, Score)", color="#C084FC"),
            "sets/set2/equipe_a/pos6": LayoutRegion(name="sets/set2/equipe_a/pos6", x0=717.1, y0=95.7, x1=737.4, y1=129.8, description="Set 2 - Équipe B - Position VI (Titulaire, Remplaçant, Score)", color="#D8B4FE"),
            "sets/set2/equipe_a/services": LayoutRegion(name="sets/set2/equipe_a/services", x0=618.1, y0=130.8, x1=736.7, y1=169.4, description="Set 2 - Équipe B - Rotations de services", color="#C084FC"),
            "sets/set2/equipe_a/timeouts": LayoutRegion(name="sets/set2/equipe_a/timeouts", x0=737.5, y0=147.4, x1=773.9, y1=164.4, description="Set 2 - Équipe B - Temps Morts", color="#DDD6FE"),
            "sets/set3/debut": LayoutRegion(name="sets/set3/debut", x0=257.9, y0=167.7, x1=274.3, y1=177.2, description="Set 3 - Heure de Début", color="#6366F1"),
            "sets/set3/fin": LayoutRegion(name="sets/set3/fin", x0=413.5, y0=167.0, x1=430.0, y1=177.2, description="Set 3 - Heure de Fin", color="#818CF8"),
            "sets/set3/equipe_a/pos1": LayoutRegion(name="sets/set3/equipe_a/pos1", x0=127.4, y0=187.7, x1=147.1, y1=222.8, description="Set 3 - Équipe A - Position I (Titulaire, Remplaçant, Score)", color="#8B5CF6"),
            "sets/set3/equipe_a/pos2": LayoutRegion(name="sets/set3/equipe_a/pos2", x0=147.8, y0=188.8, x1=166.4, y1=221.8, description="Set 3 - Équipe A - Position II (Titulaire, Remplaçant, Score)", color="#9333EA"),
            "sets/set3/equipe_a/pos3": LayoutRegion(name="sets/set3/equipe_a/pos3", x0=166.7, y0=188.8, x1=186.4, y1=221.8, description="Set 3 - Équipe A - Position III (Titulaire, Remplaçant, Score)", color="#A855F7"),
            "sets/set3/equipe_a/pos4": LayoutRegion(name="sets/set3/equipe_a/pos4", x0=186.0, y0=188.8, x1=206.4, y1=221.8, description="Set 3 - Équipe A - Position IV (Titulaire, Remplaçant, Score)", color="#C084FC"),
            "sets/set3/equipe_a/pos5": LayoutRegion(name="sets/set3/equipe_a/pos5", x0=207.1, y0=188.4, x1=225.6, y1=221.8, description="Set 3 - Équipe A - Position V (Titulaire, Remplaçant, Score)", color="#D8B4FE"),
            "sets/set3/equipe_a/pos6": LayoutRegion(name="sets/set3/equipe_a/pos6", x0=226.7, y0=187.3, x1=245.6, y1=221.8, description="Set 3 - Équipe A - Position VI (Titulaire, Remplaçant, Score)", color="#E9D5FF"),
            "sets/set3/equipe_a/services": LayoutRegion(name="sets/set3/equipe_a/services", x0=127.1, y0=222.5, x1=245.6, y1=262.8, description="Set 3 - Équipe A - Rotations de services", color="#D8B4FE"),
            "sets/set3/equipe_a/timeouts": LayoutRegion(name="sets/set3/equipe_a/timeouts", x0=245.9, y0=239.4, x1=283.0, y1=255.7, description="Set 3 - Équipe A - Temps Morts", color="#E9D5FF"),
            "sets/set3/equipe_b/pos1": LayoutRegion(name="sets/set3/equipe_b/pos1", x0=283.1, y0=188.1, x1=302.8, y1=221.8, description="Set 3 - Équipe B - Position I (Titulaire, Remplaçant, Score)", color="#7C3AED"),
            "sets/set3/equipe_b/pos2": LayoutRegion(name="sets/set3/equipe_b/pos2", x0=303.5, y0=189.1, x1=323.1, y1=222.1, description="Set 3 - Équipe B - Position II (Titulaire, Remplaçant, Score)", color="#8B5CF6"),
            "sets/set3/equipe_b/pos3": LayoutRegion(name="sets/set3/equipe_b/pos3", x0=322.8, y0=188.1, x1=342.4, y1=222.5, description="Set 3 - Équipe B - Position III (Titulaire, Remplaçant, Score)", color="#9333EA"),
            "sets/set3/equipe_b/pos4": LayoutRegion(name="sets/set3/equipe_b/pos4", x0=342.4, y0=188.1, x1=362.1, y1=222.5, description="Set 3 - Équipe B - Position IV (Titulaire, Remplaçant, Score)", color="#A855F7"),
            "sets/set3/equipe_b/pos5": LayoutRegion(name="sets/set3/equipe_b/pos5", x0=362.4, y0=188.1, x1=382.1, y1=221.8, description="Set 3 - Équipe B - Position V (Titulaire, Remplaçant, Score)", color="#C084FC"),
            "sets/set3/equipe_b/pos6": LayoutRegion(name="sets/set3/equipe_b/pos6", x0=382.1, y0=187.7, x1=402.4, y1=221.8, description="Set 3 - Équipe B - Position VI (Titulaire, Remplaçant, Score)", color="#D8B4FE"),
            "sets/set3/equipe_b/services": LayoutRegion(name="sets/set3/equipe_b/services", x0=283.1, y0=222.8, x1=401.7, y1=261.4, description="Set 3 - Équipe B - Rotations de services", color="#C084FC"),
            "sets/set3/equipe_b/timeouts": LayoutRegion(name="sets/set3/equipe_b/timeouts", x0=402.5, y0=239.4, x1=438.9, y1=256.4, description="Set 3 - Équipe B - Temps Morts", color="#DDD6FE"),
            "sets/set4/debut": LayoutRegion(name="sets/set4/debut", x0=592.9, y0=167.7, x1=609.3, y1=177.2, description="Set 4 - Heure de Début", color="#6366F1"),
            "sets/set4/fin": LayoutRegion(name="sets/set4/fin", x0=748.5, y0=167.0, x1=765.0, y1=177.2, description="Set 4 - Heure de Fin", color="#818CF8"),
            "sets/set4/equipe_b/pos1": LayoutRegion(name="sets/set4/equipe_b/pos1", x0=462.4, y0=187.7, x1=482.1, y1=222.8, description="Set 4 - Équipe A - Position I (Titulaire, Remplaçant, Score)", color="#8B5CF6"),
            "sets/set4/equipe_b/pos2": LayoutRegion(name="sets/set4/equipe_b/pos2", x0=482.8, y0=188.8, x1=501.4, y1=221.8, description="Set 4 - Équipe A - Position II (Titulaire, Remplaçant, Score)", color="#9333EA"),
            "sets/set4/equipe_b/pos3": LayoutRegion(name="sets/set4/equipe_b/pos3", x0=501.7, y0=188.8, x1=521.4, y1=221.8, description="Set 4 - Équipe A - Position III (Titulaire, Remplaçant, Score)", color="#A855F7"),
            "sets/set4/equipe_b/pos4": LayoutRegion(name="sets/set4/equipe_b/pos4", x0=521.0, y0=188.8, x1=541.4, y1=221.8, description="Set 4 - Équipe A - Position IV (Titulaire, Remplaçant, Score)", color="#C084FC"),
            "sets/set4/equipe_b/pos5": LayoutRegion(name="sets/set4/equipe_b/pos5", x0=542.1, y0=188.4, x1=560.6, y1=221.8, description="Set 4 - Équipe A - Position V (Titulaire, Remplaçant, Score)", color="#D8B4FE"),
            "sets/set4/equipe_b/pos6": LayoutRegion(name="sets/set4/equipe_b/pos6", x0=561.7, y0=187.3, x1=580.6, y1=221.8, description="Set 4 - Équipe A - Position VI (Titulaire, Remplaçant, Score)", color="#E9D5FF"),
            "sets/set4/equipe_b/services": LayoutRegion(name="sets/set4/equipe_b/services", x0=462.1, y0=222.5, x1=580.6, y1=262.8, description="Set 4 - Équipe A - Rotations de services", color="#D8B4FE"),
            "sets/set4/equipe_b/timeouts": LayoutRegion(name="sets/set4/equipe_b/timeouts", x0=580.9, y0=239.4, x1=618.0, y1=255.7, description="Set 4 - Équipe A - Temps Morts", color="#E9D5FF"),
            "sets/set4/equipe_a/pos1": LayoutRegion(name="sets/set4/equipe_a/pos1", x0=618.1, y0=188.1, x1=637.8, y1=221.8, description="Set 4 - Équipe B - Position I (Titulaire, Remplaçant, Score)", color="#7C3AED"),
            "sets/set4/equipe_a/pos2": LayoutRegion(name="sets/set4/equipe_a/pos2", x0=638.5, y0=189.1, x1=658.1, y1=222.1, description="Set 4 - Équipe B - Position II (Titulaire, Remplaçant, Score)", color="#8B5CF6"),
            "sets/set4/equipe_a/pos3": LayoutRegion(name="sets/set4/equipe_a/pos3", x0=657.8, y0=188.1, x1=677.4, y1=222.5, description="Set 4 - Équipe B - Position III (Titulaire, Remplaçant, Score)", color="#9333EA"),
            "sets/set4/equipe_a/pos4": LayoutRegion(name="sets/set4/equipe_a/pos4", x0=677.4, y0=188.1, x1=697.1, y1=222.5, description="Set 4 - Équipe B - Position IV (Titulaire, Remplaçant, Score)", color="#A855F7"),
            "sets/set4/equipe_a/pos5": LayoutRegion(name="sets/set4/equipe_a/pos5", x0=697.4, y0=188.1, x1=717.1, y1=221.8, description="Set 4 - Équipe B - Position V (Titulaire, Remplaçant, Score)", color="#C084FC"),
            "sets/set4/equipe_a/pos6": LayoutRegion(name="sets/set4/equipe_a/pos6", x0=717.1, y0=187.7, x1=737.4, y1=221.8, description="Set 4 - Équipe B - Position VI (Titulaire, Remplaçant, Score)", color="#D8B4FE"),
            "sets/set4/equipe_a/services": LayoutRegion(name="sets/set4/equipe_a/services", x0=618.1, y0=222.8, x1=736.7, y1=261.4, description="Set 4 - Équipe B - Rotations de services", color="#C084FC"),
            "sets/set4/equipe_a/timeouts": LayoutRegion(name="sets/set4/equipe_a/timeouts", x0=737.5, y0=239.4, x1=773.9, y1=256.4, description="Set 4 - Équipe B - Temps Morts", color="#DDD6FE"),
            "sets/set5/debut": LayoutRegion(name="sets/set5/debut", x0=140.3, y0=263.1, x1=156.7, y1=272.6, description="Set 5 - Heure de Début", color="#6366F1"),
            "sets/set5/fin": LayoutRegion(name="sets/set5/fin", x0=295.1, y0=262.8, x1=311.6, y1=273.0, description="Set 5 - Heure de Fin", color="#818CF8"),
            "sets/set5/equipe_b/pos1": LayoutRegion(name="sets/set5/equipe_b/pos1", x0=164.3, y0=283.5, x1=184.0, y1=317.2, description="Set 5 - Équipe B - Position I (Titulaire, Remplaçant, Score)", color="#7C3AED"),
            "sets/set5/equipe_b/pos2": LayoutRegion(name="sets/set5/equipe_b/pos2", x0=184.3, y0=283.7, x1=203.9, y1=316.7, description="Set 5 - Équipe B - Position II (Titulaire, Remplaçant, Score)", color="#8B5CF6"),
            "sets/set5/equipe_b/pos3": LayoutRegion(name="sets/set5/equipe_b/pos3", x0=204.4, y0=283.1, x1=224.0, y1=317.5, description="Set 5 - Équipe B - Position III (Titulaire, Remplaçant, Score)", color="#9333EA"),
            "sets/set5/equipe_b/pos4": LayoutRegion(name="sets/set5/equipe_b/pos4", x0=224.0, y0=283.1, x1=243.7, y1=317.5, description="Set 5 - Équipe B - Position IV (Titulaire, Remplaçant, Score)", color="#A855F7"),
            "sets/set5/equipe_b/pos5": LayoutRegion(name="sets/set5/equipe_b/pos5", x0=244.0, y0=283.5, x1=263.7, y1=317.2, description="Set 5 - Équipe B - Position V (Titulaire, Remplaçant, Score)", color="#C084FC"),
            "sets/set5/equipe_b/pos6": LayoutRegion(name="sets/set5/equipe_b/pos6", x0=263.3, y0=283.5, x1=283.6, y1=317.6, description="Set 5 - Équipe B - Position VI (Titulaire, Remplaçant, Score)", color="#D8B4FE"),
            "sets/set5/equipe_b/services": LayoutRegion(name="sets/set5/equipe_b/services", x0=164.3, y0=317.4, x1=282.9, y1=352.4, description="Set 5 - Équipe B - Rotations de services", color="#C084FC"),
            "sets/set5/equipe_b/timeouts": LayoutRegion(name="sets/set5/equipe_b/timeouts", x0=284.1, y0=334.4, x1=320.5, y1=351.4, description="Set 5 - Équipe B - Temps Morts", color="#DDD6FE"),
            "sets/set5/equipe_a/pos1": LayoutRegion(name="sets/set5/equipe_a/pos1", x0=331.4, y0=282.7, x1=351.1, y1=317.8, description="Set 5 - Équipe A - Position I (Titulaire, Remplaçant, Score)", color="#8B5CF6"),
            "sets/set5/equipe_a/pos2": LayoutRegion(name="sets/set5/equipe_a/pos2", x0=351.8, y0=283.8, x1=370.4, y1=316.8, description="Set 5 - Équipe A - Position II (Titulaire, Remplaçant, Score)", color="#9333EA"),
            "sets/set5/equipe_a/pos3": LayoutRegion(name="sets/set5/equipe_a/pos3", x0=371.5, y0=283.4, x1=391.2, y1=316.4, description="Set 5 - Équipe A - Position III (Titulaire, Remplaçant, Score)", color="#A855F7"),
            "sets/set5/equipe_a/pos4": LayoutRegion(name="sets/set5/equipe_a/pos4", x0=390.8, y0=283.8, x1=411.2, y1=316.8, description="Set 5 - Équipe A - Position IV (Titulaire, Remplaçant, Score)", color="#C084FC"),
            "sets/set5/equipe_a/pos5": LayoutRegion(name="sets/set5/equipe_a/pos5", x0=411.9, y0=283.8, x1=430.4, y1=317.2, description="Set 5 - Équipe A - Position V (Titulaire, Remplaçant, Score)", color="#D8B4FE"),
            "sets/set5/equipe_a/pos6": LayoutRegion(name="sets/set5/equipe_a/pos6", x0=431.5, y0=283.5, x1=450.4, y1=318.0, description="Set 5 - Équipe A - Position VI (Titulaire, Remplaçant, Score)", color="#E9D5FF"),
            "sets/set5/equipe_a/services": LayoutRegion(name="sets/set5/equipe_a/services", x0=331.9, y0=317.1, x1=449.6, y1=351.4, description="Set 5 - Équipe A - Rotations de services", color="#D8B4FE"),
            "sets/set5/equipe_a/timeouts": LayoutRegion(name="sets/set5/equipe_a/timeouts", x0=449.9, y0=334.0, x1=487.0, y1=350.3, description="Set 5 - Équipe A - Temps Morts", color="#E9D5FF"),
        }

    def get_region(self, name: str) -> Optional[LayoutRegion]:
        """Retourne la zone demandée avec fallback automatique d'alias pour les legacy parsers."""
        if name in self.bboxes:
            return self.bboxes[name]

        # Alias de rétro-compatibilité pour les anciens parsers
        aliases = {
            "header/equipes/a": self.bboxes.get("header/equipes/gauche"),
            "header/equipes/b": self.bboxes.get("header/equipes/droite"),
            "equipes/a/joueurs": self.bboxes.get("equipes/gauche/joueurs"),
            "equipes/a/liberos": self.bboxes.get("equipes/gauche/liberos"),
            "equipes/a/officiels": self.bboxes.get("equipes/gauche/officiels"),
            "equipes/b/joueurs": self.bboxes.get("equipes/droite/joueurs"),
            "equipes/b/liberos": self.bboxes.get("equipes/droite/liberos"),
            "equipes/b/officiels": self.bboxes.get("equipes/droite/officiels"),
            "header": LayoutRegion("header", 10.0, 10.0, 835.0, 55.0),
            "teams_header": LayoutRegion("teams_header", 10.0, 55.0, 835.0, 75.0),
            "roster_a": self.bboxes.get("equipes/gauche/joueurs"),
            "roster_b": self.bboxes.get("equipes/droite/joueurs"),
            "liberos_a": self.bboxes.get("equipes/gauche/liberos"),
            "liberos_b": self.bboxes.get("equipes/droite/liberos"),
            "officiels_a": self.bboxes.get("equipes/gauche/officiels"),
            "officiels_b": self.bboxes.get("equipes/droite/officiels"),
            "main": LayoutRegion("main", 10.0, 65.0, 410.0, 585.0),
            "secondary": LayoutRegion("secondary", 405.0, 65.0, 775.0, 420.0),
            "results": LayoutRegion("results", 420.0, 415.0, 565.0, 540.0),
            "sanctions": LayoutRegion("sanctions", 10.0, 350.0, 410.0, 425.0),
            "remarques": LayoutRegion("remarques", 130.0, 350.0, 570.0, 425.0),
            "arbitres": LayoutRegion("arbitres", 130.0, 440.0, 310.0, 500.0),
            "signatures": LayoutRegion("signatures", 570.0, 475.0, 835.0, 545.0),
        }
        print(name)
        return aliases.get(name)

    def get_pymupdf_rect(self, name: str):
        """Retourne un pymupdf.Rect pour la zone demandée."""
        import pymupdf
        reg = self.get_region(name)
        if reg:
            return pymupdf.Rect(reg.x0, reg.y0, reg.x1, reg.y1)
        return None

    def get_words_in_region(self, words: list[dict], name: str) -> list[dict]:
        """Filtre et retourne la liste des mots contenus à l'intérieur de la zone spécifiée."""
        reg = self.get_region(name)
        if not reg:
            return []
        return [
            w for w in words
            if reg.contains_bbox(
                w.get("x0", w.get("left", 0)),
                w.get("y0", w.get("top", 0)),
                w.get("x1", w.get("right", 0)),
                w.get("y1", w.get("bottom", 0)),
            )
        ]

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "version": self.version,
            "page_width": self.page_width,
            "page_height": self.page_height,
            "bboxes": {k: v.to_dict() for k, v in self.bboxes.items()},
            "main_cols": self.main_cols,
            "sec_cols": self.sec_cols,
            "res_cols": self.res_cols,
            "sig_cols": self.sig_cols,
            "x_split": self.x_split,
            "y_tolerance": self.y_tolerance,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ParserLayoutConfig:
        bboxes = {}
        if "bboxes" in data:
            for k, v in data["bboxes"].items():
                bboxes[k] = LayoutRegion.from_dict(v)

        return cls(
            name=data.get("name", "Standard FFVB Précis"),
            version=data.get("version", "3.0"),
            page_width=float(data.get("page_width", 841.89)),
            page_height=float(data.get("page_height", 595.28)),
            bboxes=bboxes,
            main_cols=[float(x) for x in data.get("main_cols", [])] or cls().main_cols,
            sec_cols=[float(x) for x in data.get("sec_cols", [])] or cls().sec_cols,
            res_cols=[float(x) for x in data.get("res_cols", [])] or cls().res_cols,
            sig_cols=[float(x) for x in data.get("sig_cols", [])] or cls().sig_cols,
            x_split=float(data.get("x_split", 700.0)),
            y_tolerance=float(data.get("y_tolerance", 3.5)),
        )

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2, ensure_ascii=False)

    @classmethod
    def from_json(cls, json_str: str) -> ParserLayoutConfig:
        return cls.from_dict(json.loads(json_str))

    def save_preset(self, path: Path | str) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(self.to_json(), encoding="utf-8")

    @classmethod
    def load_preset(cls, path: Path | str) -> ParserLayoutConfig:
        path = Path(path)
        return cls.from_json(path.read_text(encoding="utf-8"))


DEFAULT_FFVB_LAYOUT = ParserLayoutConfig()
