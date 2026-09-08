"""
Parser déterministe haute vitesse basé sur l'encadrement géométrique de zones (FastMatchSheetParser).

Extrait directement les informations des cases cibles sans dépendre d'heuristiques regex globales (<3ms).
"""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Optional, Union

import pymupdf

from pyvolley.core.models import Match
from pyvolley.parsers.base import BaseParser, ParseResult
from pyvolley.parsers.layout_config import ParserLayoutConfig, DEFAULT_FFVB_LAYOUT
from pyvolley.parsers.extractors.fast import (
    extract_fast_header,
    extract_fast_rosters,
    extract_fast_arbitres,
    extract_fast_resultats,
    extract_fast_sets,
    normalize_words,
)
from pyvolley.parsers.extractors.resultats import compute_match_played

logger = logging.getLogger(__name__)


class FastMatchSheetParser(BaseParser):
    """Parser déterministe ultra-rapide basé sur l'encadrement géométrique direct des zones FFVB."""

    @property
    def name(self) -> str:
        return "FastMatchSheetParser"

    @property
    def version(self) -> str:
        return "4.0"

    @property
    def supported_extensions(self) -> list[str]:
        return [".pdf"]

    def can_parse(self, pdf_path: Union[str, Path, bytes]) -> bool:
        """Vérifie si le document est une feuille de match FFVB valide."""
        try:
            if isinstance(pdf_path, bytes):
                doc = pymupdf.open(stream=pdf_path, filetype="pdf")
            else:
                doc = pymupdf.open(str(pdf_path))
            if not len(doc):
                doc.close()
                return False
            page = doc[0]
            text = page.get_text("text")
            doc.close()
            return "Match:" in text or "COMPETITION" in text or "FFVB" in text or "Match" in text
        except Exception:
            return False

    def __init__(self, layout_config: Optional[ParserLayoutConfig] = None):
        self._layout_config = layout_config or DEFAULT_FFVB_LAYOUT

    @property
    def layout_config(self) -> ParserLayoutConfig:
        return self._layout_config

    def parse(
        self,
        pdf_input: Union[str, Path, bytes, pymupdf.Page],
        layout_config: Optional[ParserLayoutConfig] = None,
    ) -> ParseResult:
        t0 = time.perf_counter()
        active_config = layout_config or self._layout_config

        if isinstance(pdf_input, pymupdf.Page):
            page = pdf_input
            doc_closed = False
        else:
            if isinstance(pdf_input, (str, Path)):
                doc = pymupdf.open(str(pdf_input))
            else:
                doc = pymupdf.open(stream=pdf_input, filetype="pdf")
            page = doc[0]
            doc_closed = True

        try:
            raw_words = page.get_text("words")
            sorted_words, y0_list = normalize_words(raw_words)

            image_info_list = page.get_image_info(hashes=True)
            captain_image_bboxes = [img["bbox"] for img in image_info_list if "bbox" in img]

            # 1. En-tête (Header & Résolution A/B)
            hdr = extract_fast_header(sorted_words, y0_list, active_config, image_blocks=image_info_list)

            # 2. Effectifs (Rosters A & B)
            equipe_a, equipe_b, roster_a, roster_b = extract_fast_rosters(
                sorted_words,
                y0_list,
                active_config,
                nom_gauche=hdr.nom_gauche,
                nom_droite=hdr.nom_droite,
                gauche_est_equipe_a=hdr.gauche_est_equipe_a,
                captain_image_bboxes=captain_image_bboxes,
            )

            # 3. Corps Arbitral
            arbitres_list = extract_fast_arbitres(sorted_words, y0_list, active_config)

            # 4. Résultats & Remarques
            res_data = extract_fast_resultats(sorted_words, y0_list, active_config)

            # 5. Sets 1 à 5
            sets_list = extract_fast_sets(
                sorted_words,
                y0_list,
                active_config,
                gauche_est_equipe_a=hdr.gauche_est_equipe_a,
                sets_summary=res_data.sets_summary,
            )

            # 6. Calcul des sets gagnés et score final
            sets_a = sum(1 for s in sets_list if s.vainqueur == "A")
            sets_b = sum(1 for s in sets_list if s.vainqueur == "B")

            if sets_a + sets_b > 0:
                score_final_str = f"{sets_a}/{sets_b}"
            elif res_data.score_final and "/" in res_data.score_final:
                parts = res_data.score_final.split("/")
                if len(parts) == 2 and parts[0].strip().isdigit() and parts[1].strip().isdigit():
                    sets_a, sets_b = int(parts[0].strip()), int(parts[1].strip())
                    score_final_str = f"{sets_a}/{sets_b}"
            else:
                score_final_str = res_data.score_final

            has_set_scores = len(sets_list) > 0 or bool(score_final_str)
            match_joue = compute_match_played(
                vainqueur=res_data.vainqueur,
                score_sets=score_final_str,
                has_set_scores=has_set_scores,
            )

            # Fallback de l'heure sur le début du Set 1 si non spécifiée dans la boîte date
            match_time = hdr.heure
            if not match_time and sets_list and sets_list[0].debut:
                match_time = sets_list[0].debut

            match_model = Match(
                code_match=hdr.match_code,
                date=hdr.date,
                heure=match_time,
                salle=hdr.salle,
                lieu=hdr.ville,
                competition=hdr.competition,
                organisateur=hdr.organisateur,
                journee=hdr.journee,
                genre=hdr.genre,
                categorie=hdr.categorie.value if hdr.categorie else None,
                niveau=hdr.niveau.value if hdr.niveau else None,
                division=hdr.division,
                niveau_badge=hdr.niveau_badge,
                niveau_rank=hdr.niveau_rank,
                match_joue=match_joue,
                equipe_a=equipe_a,
                equipe_b=equipe_b,
                sets_a=sets_a,
                sets_b=sets_b,
                sets=sets_list,
                arbitres=arbitres_list,
                sanctions=[],
                remarques=res_data.remarques,
                vainqueur_nom=res_data.vainqueur,
                score_final=score_final_str,
                duree_totale=res_data.duree_totale,
            )

            execution_time = (time.perf_counter() - t0) * 1000.0

            extracted_fields = sum(1 for v in [
                hdr.match_code,
                hdr.competition,
                hdr.ville,
                hdr.salle,
                hdr.date,
                equipe_a.nom,
                equipe_b.nom,
                len(arbitres_list) > 0,
                len(sets_list) > 0,
            ] if v)

            return ParseResult(
                success=True,
                match=match_model,
                parse_time_ms=execution_time,
                fields_extracted=extracted_fields,
                fields_total=12,
                field_sources={"header": "zone:header", "roster": "zone:roster", "sets": "zone:sets"},
            )
        finally:
            if doc_closed:
                doc.close()
