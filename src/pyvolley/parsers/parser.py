"""
Parser principal – orchestrateur de l'extraction de feuilles de match FFVB.

Architecture du PDF FFVB (page unique) :
  5 tables :
    Table 0 (main, ~44 rows)      : Sets 1,3,5 + sanctions + arbitres
    Table 1 (secondary, ~20 rows) : Sets 2,4
    Table 2 (players, ~4 rows)    : Roster joueurs
    Table 3 (results, ~11 rows)   : RESULTATS (scores, durées)
    Table 4 (signatures, ~3 rows) : SIGNATURES

  Header (texte libre) :
    Ligne 1 : Compétition, code match, journée
    Ligne 2 : Ville, date, heure
    Ligne 3 : Salle, genre, catégorie
    Ligne 4 : Organisation, noms d'équipe
"""

from __future__ import annotations

import logging
from time import perf_counter
from datetime import datetime
from pathlib import Path
from typing import Optional

import pdfplumber

from pyvolley.parsers.base import BaseParser, ParseResult
from pyvolley.core.models import (
    Match, Equipe, Officiel, Joueur,
    Genre, Categorie, Niveau,
)
from pyvolley.parsers.diagnostics import (
    DiagnosticCollector, Diagnostic, DiagnosticCategory as Cat,
)
from pyvolley.parsers.utils import (
    extract_club_info, extract_competition_code, try_enum, saison_year,
    normalize_club_name,
)
from pyvolley.parsers.extractors.header import extract_header
from pyvolley.parsers.extractors.equipes import (
    extract_equipes, extract_joueurs, extract_liberos,
    extract_officiels, detect_capitaines,
    mark_capitaine, mark_liberos, merge_liberos,
    recover_joueurs_from_sets, correct_team_assignment,
)
from pyvolley.parsers.extractors.sets import (
    extract_all_sets, extract_resultats_table, build_sets,
)
from pyvolley.parsers.extractors.resultats import (
    extract_resultat, is_match_played, has_detailed_scores,
    extract_arbitres, extract_sanctions,
    extract_remarques, extract_demande_non_fondee,
)
from pyvolley.parsers.validation import validate_match

logger = logging.getLogger(__name__)


_FAST_TABLE_SETTINGS = {
    "vertical_strategy": "lines_strict",
    "horizontal_strategy": "lines_strict",
    "snap_tolerance": 2,
    "join_tolerance": 2,
    "intersection_tolerance": 2,
}


class MatchSheetParser(BaseParser):
    """Parser de feuilles de match FFVB — extraction exhaustive et robuste.

    Approche :
    1. Texte plein ligne par ligne → infos header/logistique
    2. Tables structurées → joueurs, résultats, sets, arbitres
    3. Mots positionnels → libéros, officiels, capitaines
    """

    @property
    def name(self) -> str:
        return "MatchSheetParser"

    @property
    def version(self) -> str:
        return "6.1.2"

    # ================================================================
    # Point d'entrée
    # ================================================================

    def can_parse(self, pdf_path: Path) -> bool:
        pdf_path = Path(pdf_path)
        if not pdf_path.exists() or pdf_path.suffix.lower() != ".pdf":
            return False
        try:
            with pdfplumber.open(str(pdf_path)) as pdf:
                if not pdf.pages:
                    return False
                text = pdf.pages[0].extract_text_simple() or ""
                markers = ["Match:", "Vainqueur", "RESULTATS", "SET"]
                return sum(1 for m in markers if m in text) >= 2
        except Exception:
            return False

    def parse(self, pdf_path: Path) -> ParseResult:
        pdf_path = Path(pdf_path)
        start = perf_counter()
        result = ParseResult(success=False)
        diag = DiagnosticCollector()

        try:
            if not pdf_path.exists():
                result.add_error(f"Fichier non trouvé: {pdf_path}")
                return result

            with pdfplumber.open(str(pdf_path)) as pdf:
                if not pdf.pages:
                    result.add_error("PDF vide")
                    return result

                page = pdf.pages[0]
                words = page.extract_words()
                full_text = page.extract_text() or ""
                if not full_text.strip():
                    result.add_error("Aucun texte extrait du PDF")
                    return result
                lines = full_text.splitlines()

                tables = page.extract_tables(table_settings=_FAST_TABLE_SETTINGS)
                if len(tables) < 3:
                    tables = page.extract_tables()
                tidx = _identify_tables(tables)
                fields_count = 0

                # ── Phase 1 : Informations générales ──

                header = extract_header(lines)
                fields_count += sum(1 for v in header.values() if v)

                equipes_info = extract_equipes(tidx, words, lines)
                fields_count += sum(1 for v in equipes_info.values() if v)

                # ── Phase 2 : Personnes ──

                joueurs_a, joueurs_b, duplication_detected = extract_joueurs(tidx)
                fields_count += len(joueurs_a) + len(joueurs_b)

                liberos_a, liberos_b = extract_liberos(words)
                mark_liberos(joueurs_a, liberos_a)
                mark_liberos(joueurs_b, liberos_b)

                off_a, off_b = extract_officiels(words)

                cap_a, cap_b = detect_capitaines(
                    None, None, words, tidx, page=page,
                )
                mark_capitaine(joueurs_a, cap_a)
                mark_capitaine(joueurs_b, cap_b)

                arbitres = extract_arbitres(tidx)
                fields_count += len(arbitres)

                # ── Phase 3 : Résultats & détection match joué ──

                resultat = extract_resultat(lines, tidx)
                fields_count += sum(1 for v in resultat.values() if v)

                match_joue = is_match_played(resultat)
                has_detail_score = has_detailed_scores(resultat)
                saison_str = header.get("saison")
                sy = saison_year(saison_str)
                is_modern = sy is not None and sy >= 2024

                res_data, duree_from_table = extract_resultats_table(tidx)
                if duree_from_table and not resultat.get("duree_totale"):
                    resultat["duree_totale"] = duree_from_table

                has_set_scores = any(
                    (r.get('points_a') or 0) > 0
                    or (r.get('points_b') or 0) > 0
                    for r in res_data
                )

                if match_joue and not has_detail_score and not has_set_scores:
                    tables_fallback = page.extract_tables()
                    tidx_fallback = _identify_tables(tables_fallback)
                    fallback_res_data, fallback_duree = extract_resultats_table(tidx_fallback)
                    fallback_has_set_scores = any(
                        (row.get('points_a') or 0) > 0
                        or (row.get('points_b') or 0) > 0
                        for row in fallback_res_data
                    )
                    if fallback_has_set_scores:
                        tidx = tidx_fallback
                        res_data = fallback_res_data
                        has_set_scores = True
                        if fallback_duree and not resultat.get("duree_totale"):
                            resultat["duree_totale"] = fallback_duree

                # ── Phase 4 : Détails des sets ──
                sets_detailed: list[dict] = []
                if has_detail_score or has_set_scores:
                    sets_detailed = extract_all_sets(tidx)
                else:
                    logger.debug(
                        "Pas de données de sets détaillées – parsing des "
                        "sections SET ignoré : %s", pdf_path.name,
                    )

                # Construction des Sets
                sets, set_warnings = build_sets(
                    sets_detailed, res_data, resultat,
                    equipes_info.get("equipe_a", ""),
                    equipes_info.get("equipe_b", ""),
                )
                for w in set_warnings:
                    diag.parse_warning(Cat.COHERENCE, w)
                fields_count += len(sets) * 5

                # ── Phase 5 : Sanctions, remarques ──

                sanctions, sanc_warnings = extract_sanctions(tidx)
                for w in sanc_warnings:
                    diag.data_warning(Cat.SANCTION, w)

                remarques = extract_remarques(tidx)
                demande_nf = extract_demande_non_fondee(tidx)

                # ── Fallback heure : utiliser le début du 1er set ──
                if not header.get("heure_obj") and sets:
                    first_set = next(
                        (s for s in sets if s.debut is not None), None,
                    )
                    if first_set and first_set.debut:
                        header["heure_obj"] = first_set.debut
                        header["heure"] = first_set.debut.strftime("%Hh%M")

                # ── Phase 6 : Récupération joueurs manquants ──

                if duplication_detected and sets:
                    # Corriger les joueurs mal assignés (garbled cells)
                    correct_team_assignment(joueurs_a, joueurs_b, sets)

                    recovered_a, recovered_b = recover_joueurs_from_sets(
                        joueurs_a, joueurs_b, sets,
                    )
                    if recovered_a or recovered_b:
                        joueurs_a.extend(recovered_a)
                        joueurs_b.extend(recovered_b)
                        nums_a = sorted(
                            j.numero for j in recovered_a if j.numero
                        )
                        nums_b = sorted(
                            j.numero for j in recovered_b if j.numero
                        )
                        parts: list[str] = []
                        if nums_a:
                            parts.append(f"A: #{', #'.join(nums_a)}")
                        if nums_b:
                            parts.append(f"B: #{', #'.join(nums_b)}")
                        diag.data_info(
                            Cat.DUPLICATION,
                            f"Feuille dupliquée détectée — "
                            f"{len(recovered_a) + len(recovered_b)} "
                            f"joueur(s) récupéré(s) depuis les formations "
                            f"({'; '.join(parts)})",
                        )

                # ── Phase 7 : Construction du Match ──

                match = _build_match(
                    header=header,
                    equipes_info=equipes_info,
                    resultat=resultat,
                    joueurs_a=joueurs_a, joueurs_b=joueurs_b,
                    liberos_a=liberos_a, liberos_b=liberos_b,
                    off_a=off_a, off_b=off_b,
                    sets=sets,
                    arbitres=arbitres,
                    sanctions=sanctions,
                    remarques=remarques,
                    demande_nf=demande_nf,
                    pdf_path=pdf_path,
                    match_joue=match_joue,
                )

                result.success = True
                result.match = match
                result.fields_extracted = min(fields_count, 40)
                result.fields_total = 40

                # ── Warnings contextuels ──
                if not match_joue:
                    diag.data_info(
                        Cat.MATCH_STATUS,
                        "Match non joué ou annulé (aucun vainqueur)",
                    )
                elif (match_joue and not has_detail_score
                      and not has_set_scores and is_modern):
                    diag.data_warning(
                        Cat.SCORE,
                        "Match joué mais scores de sets absents "
                        "(attendus pour saison >= 2024-2025)",
                    )

                # ── Validation structurée ──
                diag.extend(validate_match(match, is_modern=is_modern))

                # ── Peupler le résultat ──
                result.diagnostics = diag.all

        except Exception as e:
            result.add_error(f"Erreur de parsing: {e}")
            import traceback
            result.add_error(traceback.format_exc())
        finally:
            result.parse_time_ms = (perf_counter() - start) * 1000
            self._record_result(result)

        return result


# =====================================================================
# Helpers internes (pas de self, fonctions pures)
# =====================================================================


def _identify_tables(tables: list) -> dict:
    """Identifie les 5 tables du PDF FFVB par contenu."""
    idx: dict = {
        'main': None, 'secondary': None,
        'players': None, 'results': None, 'signatures': None,
    }

    for table in tables:
        if not table or len(table) < 2:
            continue
        sample = ' '.join(
            str(c) for row in table[:4] if row for c in row if c
        )
        if 'RESULTATS' in sample:
            idx['results'] = table
        elif 'Nom Prénom' in sample and 'Licence' in sample:
            idx['players'] = table
        elif 'SIGNATURES' in sample:
            idx['signatures'] = table

    remaining = [
        t for t in tables
        if t and t not in (idx['results'], idx['players'], idx['signatures'])
    ]
    remaining.sort(
        key=lambda t: len(t) * max((len(r) for r in t if r), default=0),
        reverse=True,
    )
    if remaining:
        idx['main'] = remaining[0]
    if len(remaining) >= 2:
        idx['secondary'] = remaining[1]

    return idx


def _build_match(
    *,
    header: dict,
    equipes_info: dict,
    resultat: dict,
    joueurs_a: list[Joueur],
    joueurs_b: list[Joueur],
    liberos_a: list[Joueur],
    liberos_b: list[Joueur],
    off_a: list[Officiel],
    off_b: list[Officiel],
    sets: list,
    arbitres: list,
    sanctions: list,
    remarques: Optional[str],
    demande_nf: Optional[str],
    pdf_path: Path,
    match_joue: bool,
) -> Match:
    """Construit l'objet Match final."""
    nom_a = equipes_info.get("equipe_a") or "Équipe A"
    nom_b = equipes_info.get("equipe_b") or "Équipe B"

    club_nom_a, num_equipe_a = extract_club_info(nom_a)
    club_nom_b, num_equipe_b = extract_club_info(nom_b)

    # Normaliser aussi les noms d’équipe (VB uniformé)
    nom_a = normalize_club_name(nom_a)
    nom_b = normalize_club_name(nom_b)

    all_joueurs_a = merge_liberos(joueurs_a, liberos_a)
    all_joueurs_b = merge_liberos(joueurs_b, liberos_b)

    equipe_a = Equipe(
        nom=nom_a,
        club_nom=club_nom_a,
        numero_equipe=num_equipe_a,
        joueurs=all_joueurs_a,
        officiels=off_a,
    )
    equipe_b = Equipe(
        nom=nom_b,
        club_nom=club_nom_b,
        numero_equipe=num_equipe_b,
        joueurs=all_joueurs_b,
        officiels=off_b,
    )

    # Calcul sets gagnés
    sets_a = sets_b = 0
    computed_a = sum(
        1 for s in sets
        if s.score_a is not None and s.score_b is not None
        and s.score_a > s.score_b
    )
    computed_b = sum(
        1 for s in sets
        if s.score_a is not None and s.score_b is not None
        and s.score_b > s.score_a
    )
    if computed_a + computed_b > 0:
        sets_a, sets_b = computed_a, computed_b
    elif sc := resultat.get("score_final"):
        try:
            a, b = sc.split("/")
            sets_a, sets_b = int(a), int(b)
        except Exception:
            pass

    genre = try_enum(Genre, header.get("genre"))
    categorie = try_enum(Categorie, header.get("categorie"))
    niveau = try_enum(Niveau, header.get("niveau"))

    # Remarques enrichies
    all_remarks: list[str] = []
    if remarques:
        all_remarks.append(remarques)
    if demande_nf:
        all_remarks.append(f"Demande non fondée: {demande_nf}")
    full_remarks = ' | '.join(all_remarks) if all_remarks else None

    code_match = header.get("code_match") or "UNKNOWN"
    competition_code = extract_competition_code(code_match)

    has_details = any(
        s.score_a is not None and s.score_b is not None
        and (s.score_a > 0 or s.score_b > 0)
        for s in sets
    )

    score_source: Optional[str] = None
    if has_details:
        score_source = "pdf"
    elif match_joue and (sets_a + sets_b > 0):
        score_source = "pdf"

    return Match(
        code_match=code_match,
        ligue=header.get("ligue"),
        competition=header.get("competition"),
        competition_code=competition_code,
        journee=header.get("journee"),
        saison=header.get("saison"),
        date=header.get("date_obj"),
        heure=header.get("heure_obj"),
        lieu=header.get("lieu"),
        salle=header.get("salle"),
        genre=genre,
        categorie=categorie,
        niveau=niveau,
        organisateur=header.get("organisateur"),
        equipe_a=equipe_a,
        equipe_b=equipe_b,
        sets=sets,
        vainqueur_nom=resultat.get("vainqueur"),
        score_final=(
            f"{sets_a}/{sets_b}"
            if sets_a + sets_b > 0
            else resultat.get("score_final")
        ),
        sets_a=sets_a,
        sets_b=sets_b,
        duree_totale=resultat.get("duree_totale"),
        match_joue=match_joue,
        has_details=has_details,
        score_source=score_source,
        arbitres=arbitres,
        sanctions=sanctions,
        remarques=full_remarks,
        source_pdf=str(pdf_path),
        parsed_at=datetime.now(),
    )
