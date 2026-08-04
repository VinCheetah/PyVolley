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


_JOURS_ALT = '|'.join(JOURS_SEMAINE)
_MATCH_CODE_PATTERN = re.compile(r'Match:\s*(\w+)')
_JOURNEE_PATTERN = re.compile(r'Jour:\s*(\d+)')
_LIGUE_FALLBACK_PATTERN = re.compile(r'Ligue\s+(\w[\w\s-]*?)(?:\s+Match:|\s*$)')
_VILLE_PATTERN = re.compile(r'Ville:\s*(.+?)\s+(?:' + _JOURS_ALT + r')\s')
_DATE_PATTERN = re.compile(r'(' + _JOURS_ALT + r')\s+(\d{1,2})\s+(\w+)\s+(\d{4})')
_HEURE_PATTERN = re.compile(r'à\s+(\d{1,2})h(\d{2})')
_SALLE_PATTERN = re.compile(
    r'Salle:\s*(.+?)(?:\s+(?:SENIOR|MASCULIN|FÉMININ|FEMININ|MIXTE|M\d{2}|U\d{2})|\s*$)',
)
_CATEGORIE_PATTERN = re.compile(r'\b(M\d{2}|U\d{2})\b')


def extract_header(lines: list[str]) -> dict:
    """Parse le header depuis les premières lignes du texte.

    Supports les lignes fusions (pdfplumber) et segmentées (PyMuPDF).
    """
    header: dict = {
        "competition": None, "code_match": None, "journee": None,
        "date": None, "date_obj": None, "heure": None, "heure_obj": None,
        "lieu": None, "salle": None, "genre": None, "categorie": None,
        "saison": None, "ligue": None, "organisation": None,
        "organisateur": None, "niveau": None,
        "division": None, "type_competition": None, "phase": None,
    }

    clean_lines = [l.strip() for l in lines if l and l.strip()]

    for i, line in enumerate(clean_lines[:12]):
        # ── Code match & journée ──
        if 'Match:' in line:
            if m := _MATCH_CODE_PATTERN.search(line):
                header["code_match"] = m.group(1)
            if m := _JOURNEE_PATTERN.search(line):
                header["journee"] = m.group(1)
            comp_part = line.split('Match:')[0].strip().rstrip('-').strip()
            if comp_part:
                header["competition"] = comp_part
            elif i > 0:
                prev = clean_lines[i - 1]
                if not any(kw in prev for kw in ('Ligue', 'Comité', 'Comite', 'FFVB', 'Match:')):
                    header["competition"] = prev

        # ── Ville, date, heure ──
        if 'Ville:' in line:
            header.update(_parse_ville_date_line(line))
            if not header.get("lieu"):
                lieu_raw = line.split('Ville:')[-1].strip()
                lieu_clean = re.sub(r'\s+(?:' + _JOURS_ALT + r').*$', '', lieu_raw, flags=re.IGNORECASE).strip()
                if lieu_clean and lieu_clean not in JOURS_SEMAINE:
                    header["lieu"] = lieu_clean

        if (
            not header.get("date_obj")
            and any(day in line for day in JOURS_SEMAINE)
        ) or (not header.get("heure_obj") and 'h' in line and ('à' in line or ':' in line or re.search(r'\b\d{1,2}h\d{2}\b', line))):
            frag = _parse_date_time_fragment(line)
            if frag:
                header.update(frag)

        # ── Salle ──
        if 'Salle:' in line:
            header.update(_parse_salle_line(line))

        # ── Genre & Catégorie (détectés sur n'importe quelle ligne d'en-tête) ──
        upper = line.upper()
        if not header.get("genre"):
            if 'MASCULIN' in upper:
                header["genre"] = "MASCULIN"
            elif 'FÉMININ' in upper or 'FEMININ' in upper:
                header["genre"] = "FEMININ"
            elif 'MIXTE' in upper:
                header["genre"] = "MIXTE"

        if not header.get("categorie"):
            if 'SENIOR' in upper:
                header["categorie"] = "SENIOR"
            elif cm := _CATEGORIE_PATTERN.search(upper):
                header["categorie"] = cm.group(1)

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
            elif m := _LIGUE_FALLBACK_PATTERN.search(line):
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

    if m := _VILLE_PATTERN.search(line):
        lieu = m.group(1).strip()
        if lieu and lieu not in JOURS_SEMAINE and not any(day in lieu.upper() for day in ('SAMEDI', 'DIMANCHE', 'LUNDI', 'MARDI', 'MERCREDI', 'JEUDI', 'VENDREDI')):
            info["lieu"] = lieu

    if dm := _DATE_PATTERN.search(line):
        jour_sem, jour_s, mois_s, annee_s = dm.groups()
        jour = int(jour_s)
        annee = int(annee_s)
        info["date"] = f"{jour_sem} {jour} {mois_s.capitalize()} {annee}"
        mois_num = MOIS_MAP.get(mois_s.lower(), 1)
        try:
            info["date_obj"] = dt_date(annee, mois_num, jour)
        except ValueError:
            pass

    if hm := _HEURE_PATTERN.search(line):
        h, mn = int(hm.group(1)), int(hm.group(2))
        info["heure"] = f"{h:02d}:{mn:02d}:00"
        try:
            info["heure_obj"] = dt_time(h, mn)
        except ValueError:
            pass

    if not info.get("lieu") and info.get("date"):
        info["lieu"] = info["date"]

    return info


def _parse_date_time_fragment(line: str) -> dict:
    """Parse une ligne fragmentée contenant uniquement date/heure.

    Cas fréquent avec ``extract_text_simple`` :
    ``Ville: X`` sur une ligne puis ``Samedi 10 Octobre 2025 à 20h00``
    sur la suivante.
    """
    info: dict = {}

    if dm := _DATE_PATTERN.search(line):
        jour_sem, jour_s, mois_s, annee_s = dm.groups()
        jour = int(jour_s)
        annee = int(annee_s)
        info["date"] = f"{jour_sem} {jour} {mois_s.capitalize()} {annee}"
        mois_num = MOIS_MAP.get(mois_s.lower(), 1)
        try:
            info["date_obj"] = dt_date(annee, mois_num, jour)
        except ValueError:
            pass

    if hm := _HEURE_PATTERN.search(line):
        h, mn = int(hm.group(1)), int(hm.group(2))
        info["heure"] = f"{h:02d}:{mn:02d}:00"
        try:
            info["heure_obj"] = dt_time(h, mn)
        except ValueError:
            pass

    return info


def _parse_salle_line(line: str) -> dict:
    """Parse ``'Salle: CSU - GRAND GYMNASE SENIOR | MASCULIN'``."""
    info: dict = {}

    if m := _SALLE_PATTERN.search(line):
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
    elif cm := _CATEGORIE_PATTERN.search(upper):
        info["categorie"] = cm.group(1)

    return info
