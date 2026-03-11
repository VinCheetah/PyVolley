"""
Extraction des informations d'en-tête de la feuille de match.

Responsable de : compétition, code match, journée, date, heure,
lieu, salle, genre, catégorie, saison, ligue, organisateur, niveau,
type de compétition, phase, division.

Utilise le module ``competition_info`` pour une extraction riche et
cohérente des métadonnées de compétition à partir du nom de la
compétition tel qu'il apparaît dans le header du PDF FFVB.
"""

from __future__ import annotations

import re
from datetime import date as dt_date, time as dt_time
from typing import Optional

from pyvolley.parsers.constants import MOIS_MAP, JOURS_SEMAINE
from pyvolley.parsers.utils import detect_niveau, extract_organisateur


def extract_header(lines: list[str]) -> dict:
    """Parse le header depuis les premières lignes du texte.

    Lignes typiques :
      [0] ``"EMA - ELITE MASCULINE - POULE A Match: EMA001 - Jour: 01"``
      [1] ``"Ville: SAINT MARTIN D'HÈRES Samedi 20 Septembre 2025 à 20h30"``
      [2] ``"Salle: CSU - GRAND GYMNASE SENIOR | MASCULIN"``
      [3] ``"Compétitions Nationales SENIORS GRENOBLE V.UNIVERSITE CLUB …"``
    """
    header: dict = {
        "competition": None, "code_match": None, "journee": None,
        "date": None, "date_obj": None, "heure": None, "heure_obj": None,
        "lieu": None, "salle": None, "genre": None, "categorie": None,
        "saison": None, "ligue": None, "organisation": None,
        "organisateur": None, "niveau": None,
        "division": None, "type_competition": None, "phase": None,
    }

    for line in lines[:8]:
        line = line.strip()

        # ── Code match & journée ──
        if 'Match:' in line:
            if m := re.search(r'Match:\s*(\w+)', line):
                header["code_match"] = m.group(1)
            if m := re.search(r'Jour:\s*(\d+)', line):
                header["journee"] = m.group(1)
            comp_part = line.split('Match:')[0].strip().rstrip('-').strip()
            if comp_part:
                header["competition"] = comp_part

        # ── Ville, date, heure ──
        if 'Ville:' in line:
            header.update(_parse_ville_date_line(line))

        # ── Salle, genre, catégorie ──
        if 'Salle:' in line:
            header.update(_parse_salle_line(line))

        # ── Organisation / ligue / organisateur ──
        if 'Compétitions' in line or 'Compétition' in line:
            header["organisation"] = "Compétitions Nationales"
            org = extract_organisateur(line)
            if org:
                header["organisateur"] = org
        elif 'Comité' in line or 'Comite' in line:
            org = extract_organisateur(line)
            if org:
                header["organisateur"] = org
                header["organisation"] = org
            else:
                cm = re.match(r'(Comité[^A-Z]*?)\s+[A-Z]', line)
                if cm:
                    header["organisation"] = cm.group(1).strip()
                    header["organisateur"] = cm.group(1).strip()
                else:
                    header["organisation"] = line.split('  ')[0].strip()
                    header["organisateur"] = line.split('  ')[0].strip()
        elif 'Ligue' in line:
            org = extract_organisateur(line)
            if org:
                header["ligue"] = org
                header["organisation"] = org
                header["organisateur"] = org
            elif m := re.search(r'Ligue\s+(\w[\w\s-]*?)(?:\s+Match:|\s*$)', line):
                ligue_name = m.group(1).strip()
                if len(ligue_name) > 1:
                    header["ligue"] = f"Ligue {ligue_name}"
                    header["organisation"] = f"Ligue {ligue_name}"
                    header["organisateur"] = f"Ligue {ligue_name}"

    # ── Saison depuis la date ──
    if d := header.get("date_obj"):
        header["saison"] = (
            f"{d.year}-{d.year + 1}" if d.month >= 8
            else f"{d.year - 1}-{d.year}"
        )

    # ── Enrichissement via competition_info ──
    _enrich_from_competition_name(header)

    return header


# ── Enrichissement via competition_info ──────────────────────────────


def _enrich_from_competition_name(header: dict) -> None:
    """Enrichit le header avec les métadonnées de compétition.

    Utilise le module ``competition_info`` pour analyser le nom de la
    compétition et en extraire : genre, catégorie, niveau, division,
    type de compétition et phase.

    Les valeurs déjà présentes (ex: genre détecté depuis la ligne Salle)
    ne sont pas écrasées.
    """
    competition = header.get("competition")
    if not competition:
        return

    try:
        from pyvolley.scrapers.ffvb.competition_info import parse_competition_name

        # Déterminer le type d'entité organisatrice pour le fallback
        entite_type = None
        organisateur = header.get("organisateur") or ""
        org_lower = organisateur.lower()
        if "nationale" in org_lower or "compétition" in org_lower:
            entite_type = "nationale"
        elif "ligue" in org_lower:
            entite_type = "ligue"
        elif "comité" in org_lower or "comite" in org_lower:
            entite_type = "comite"

        meta = parse_competition_name(
            competition,
            poule_code=header.get("code_match"),
            entite_type=entite_type,
        )

        # Remplir les champs manquants
        if not header.get("genre") and meta.genre:
            header["genre"] = meta.genre
        if not header.get("categorie") and meta.categorie_age:
            header["categorie"] = meta.categorie_age
        if not header.get("niveau") and meta.niveau:
            header["niveau"] = meta.niveau
        if not header.get("division") and meta.division:
            header["division"] = meta.division
        if not header.get("type_competition") and meta.type_competition:
            header["type_competition"] = meta.type_competition
        if not header.get("phase") and meta.phase:
            header["phase"] = meta.phase

    except Exception:
        # Fallback : utiliser l'ancien detect_niveau si competition_info échoue
        if not header.get("niveau"):
            header["niveau"] = detect_niveau(
                header.get("competition"),
                header.get("organisateur"),
            )


# ── Sous-fonctions privées ────────────────────────────────────────────


def _parse_ville_date_line(line: str) -> dict:
    """Parse ``'Ville: SAINT MARTIN D'HÈRES Samedi 20 Septembre 2025 à 20h30'``."""
    info: dict = {}

    if m := re.search(
        r'Ville:\s*(.+?)\s+(?:' + '|'.join(JOURS_SEMAINE) + r')\s',
        line,
    ):
        lieu = m.group(1).strip()
        if lieu and lieu not in JOURS_SEMAINE:
            info["lieu"] = lieu

    if dm := re.search(
        r'(' + '|'.join(JOURS_SEMAINE) + r')\s+(\d{1,2})\s+(\w+)\s+(\d{4})',
        line,
    ):
        jour_sem, jour_s, mois_s, annee_s = dm.groups()
        jour = int(jour_s)
        annee = int(annee_s)
        info["date"] = f"{jour_sem} {jour} {mois_s.capitalize()} {annee}"
        mois_num = MOIS_MAP.get(mois_s.lower(), 1)
        try:
            info["date_obj"] = dt_date(annee, mois_num, jour)
        except ValueError:
            pass

    if hm := re.search(r'à\s+(\d{1,2})h(\d{2})', line):
        h, mn = int(hm.group(1)), int(hm.group(2))
        info["heure"] = f"{h}h{mn:02d}"
        try:
            info["heure_obj"] = dt_time(h, mn)
        except ValueError:
            pass

    return info


def _parse_salle_line(line: str) -> dict:
    """Parse ``'Salle: CSU - GRAND GYMNASE SENIOR | MASCULIN'``."""
    info: dict = {}

    if m := re.search(
        r'Salle:\s*(.+?)(?:\s+(?:SENIOR|MASCULIN|FÉMININ|FEMININ|MIXTE|M\d{2}|U\d{2})|\s*$)',
        line,
    ):
        info["salle"] = m.group(1).strip()

    upper = line.upper()
    if 'MASCULIN' in upper:
        info["genre"] = "MASCULIN"
    elif 'FÉMININ' in upper or 'FEMININ' in upper:
        info["genre"] = "FEMININ"
    elif 'MIXTE' in upper:
        info["genre"] = "MIXTE"

    if 'SENIOR' in upper:
        info["categorie"] = "SENIOR"
    elif cm := re.search(r'\b(M\d{2}|U\d{2})\b', upper):
        info["categorie"] = cm.group(1)

    return info
