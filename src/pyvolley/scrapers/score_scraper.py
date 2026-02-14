"""
Scraper de scores en ligne pour compléter les données manquantes.

Récupère les résultats (score en sets et scores détaillés par set) depuis
les pages de calendrier du site FFVB (ffvbbeach.org).

Utilisation typique :
  1. Le parser PDF extrait un match sans détails (feuille pré-2024).
  2. Ce module récupère les scores depuis le calendrier en ligne.
  3. L'import service met à jour le match en DB avec ``score_source="online"``.
"""

import logging
import re
from dataclasses import dataclass
from typing import Optional, Iterator
from urllib.parse import urljoin, urlencode

from pyvolley.scrapers.ffvb import FFVBScraper

logger = logging.getLogger(__name__)


@dataclass
class OnlineMatchScore:
    """Score d'un match récupéré en ligne."""
    code_match: str
    entity_code: str
    poule_code: str
    saison: str

    # Résultat
    equipe_a: Optional[str] = None
    equipe_b: Optional[str] = None
    score_sets: Optional[str] = None   # "3/1"
    sets_a: int = 0
    sets_b: int = 0
    set_scores: Optional[list[tuple[int, int]]] = None  # [(25,20), (22,25), ...]
    vainqueur: Optional[str] = None
    date: Optional[str] = None
    journee: Optional[str] = None

    def __post_init__(self):
        if self.set_scores is None:
            self.set_scores = []

    @property
    def is_complete(self) -> bool:
        """True si les scores sont présents et cohérents."""
        return (
            self.sets_a + self.sets_b > 0
            and self.set_scores is not None
            and len(self.set_scores) == self.sets_a + self.sets_b
        )


class FFVBScoreScraper:
    """
    Scrape les scores de matchs depuis les pages de calendrier FFVB.

    Le calendrier contient généralement :
    - Les noms des équipes
    - Le score en sets (ex: 3-1)
    - Les scores détaillés par set (ex: 25-20 22-25 25-18 25-15)

    Usage::

        scraper = FFVBScoreScraper()
        scores = scraper.get_scores_for_poule("ABCCS", "EMA", "2022/2023")
        for score in scores:
            print(score.code_match, score.score_sets, score.set_scores)
    """

    def __init__(self, ffvb_scraper: Optional[FFVBScraper] = None):
        self._scraper = ffvb_scraper or FFVBScraper()

    def get_scores_for_poule(
        self,
        entity_code: str,
        poule_code: str,
        saison: str,
    ) -> list[OnlineMatchScore]:
        """
        Récupère tous les scores d'une poule depuis le calendrier complet.

        Args:
            entity_code: Code de l'entité (ex: "ABCCS", "LIGU")
            poule_code: Code de la poule (ex: "EMA", "DFA")
            saison: Saison au format YYYY/YYYY (ex: "2022/2023")

        Returns:
            Liste des OnlineMatchScore trouvés.
        """
        params = {
            "saison": saison,
            "codent": entity_code,
            "poule": poule_code,
            "calend": "COMPLET",
        }
        url = urljoin(
            self._scraper.base_url,
            f"vbspo_calendrier.php?{urlencode(params)}",
        )

        try:
            soup = self._scraper._get_soup(url)
        except Exception as e:
            logger.warning(
                "Impossible de récupérer le calendrier %s/%s %s : %s",
                entity_code, poule_code, saison, e,
            )
            return []

        return self._parse_calendar_page(
            soup, entity_code, poule_code, saison,
        )

    def _parse_calendar_page(
        self, soup, entity_code: str, poule_code: str, saison: str,
    ) -> list[OnlineMatchScore]:
        """Parse la page de calendrier FFVB pour extraire les scores.

        La page contient typiquement un tableau avec :
          - Colonnes : Journée, Match, Equipe A, Set 1..5, Equipe B, Score
          - Ou variantes avec les scores inline
        """
        scores: list[OnlineMatchScore] = []
        seen: set[str] = set()

        # Chercher tous les tableaux
        for table in soup.find_all("table"):
            rows = table.find_all("tr")
            if len(rows) < 2:
                continue

            for row in rows:
                cells = row.find_all(["td", "th"])
                if len(cells) < 4:
                    continue

                cell_texts = [c.get_text(strip=True) for c in cells]
                row_text = " ".join(cell_texts)

                # Chercher le code match dans la ligne
                code_match = None
                for ct in cell_texts:
                    # Codes FFVB : lettres + chiffres, ex: EMA001, 3FE003
                    if re.match(r'^[A-Z0-9]{2,6}\d{2,4}$', ct, re.I):
                        code_match = ct.upper()
                        break

                # Chercher aussi dans les liens (formulaires vers fdme)
                if not code_match:
                    for link in row.find_all("a", href=True):
                        href = link["href"]
                        if m := re.search(r'codmatch=([A-Z0-9]+)', href, re.I):
                            code_match = m.group(1).upper()
                            break
                    for form in row.find_all("form"):
                        action = form.get("action", "")
                        if m := re.search(r'codmatch=([A-Z0-9]+)', action, re.I):
                            code_match = m.group(1).upper()
                            break

                if not code_match or code_match in seen:
                    continue

                # Chercher les scores dans la ligne
                score_data = self._extract_scores_from_row(cell_texts)
                if not score_data:
                    continue

                seen.add(code_match)

                oms = OnlineMatchScore(
                    code_match=code_match,
                    entity_code=entity_code,
                    poule_code=poule_code,
                    saison=saison,
                    equipe_a=score_data.get("equipe_a"),
                    equipe_b=score_data.get("equipe_b"),
                    score_sets=score_data.get("score_sets"),
                    sets_a=score_data.get("sets_a", 0),
                    sets_b=score_data.get("sets_b", 0),
                    set_scores=score_data.get("set_scores", []),
                    vainqueur=score_data.get("vainqueur"),
                )
                scores.append(oms)

        logger.info(
            "Calendrier %s/%s %s : %d scores récupérés",
            entity_code, poule_code, saison, len(scores),
        )
        return scores

    @staticmethod
    def _extract_scores_from_row(cells: list[str]) -> Optional[dict]:
        """Extrait les scores depuis les cellules d'une ligne de calendrier.

        Formats courants :
          - ["01", "EMA001", "Club A", "3", "25-20 25-22 ...", "1", "Club B"]
          - ["01", "EMA001", "Club A", "3-1", "Club B", "25-20", "25-22", ...]
          - Scores inline: "3 - 1 (25-20 / 22-25 / 25-18 / 25-15)"
        """
        data: dict = {}
        set_scores: list[tuple[int, int]] = []

        # Trouver le score en sets (pattern X-Y ou X/Y ou X - Y)
        sets_pattern = re.compile(r'^(\d)\s*[-/]\s*(\d)$')
        team_names: list[str] = []
        score_sets_idx = None

        for i, ct in enumerate(cells):
            ct = ct.strip()
            if not ct:
                continue

            # Score en sets
            if m := sets_pattern.match(ct):
                sa, sb = int(m.group(1)), int(m.group(2))
                if 0 <= sa <= 3 and 0 <= sb <= 3 and sa + sb >= 3:
                    data["sets_a"] = sa
                    data["sets_b"] = sb
                    data["score_sets"] = f"{sa}/{sb}"
                    score_sets_idx = i

            # Scores de set inline (ex: "25-20")
            elif m := re.match(r'^(\d{1,2})\s*-\s*(\d{1,2})$', ct):
                a, b = int(m.group(1)), int(m.group(2))
                if 15 <= max(a, b) <= 40 and min(a, b) >= 0:
                    set_scores.append((a, b))

            # Scores de set groupés : "25-20 22-25 25-18"
            elif re.match(r'(\d{1,2}-\d{1,2}\s*){2,}', ct):
                for sm in re.finditer(r'(\d{1,2})-(\d{1,2})', ct):
                    a, b = int(sm.group(1)), int(sm.group(2))
                    if 15 <= max(a, b) <= 40:
                        set_scores.append((a, b))

            # Noms d'équipe (texte long, pas un nombre, pas un score)
            elif (len(ct) > 3 and not ct.isdigit()
                  and not re.match(r'^\d{1,2}[-/]\d{1,2}$', ct)
                  and ct not in ("Forfait", "Reporté")):
                team_names.append(ct)

        if not data.get("score_sets"):
            # Pas de score en sets trouvé → pas de résultat
            return None

        # Assigner les noms d'équipe
        if len(team_names) >= 2:
            # Prendre les 2 noms les plus longs (les vrais noms d'équipe)
            team_names.sort(key=len, reverse=True)
            data["equipe_a"] = team_names[0]
            data["equipe_b"] = team_names[1]

        if set_scores:
            data["set_scores"] = set_scores

        # Déterminer le vainqueur
        if data.get("sets_a", 0) > data.get("sets_b", 0):
            data["vainqueur"] = data.get("equipe_a")
        elif data.get("sets_b", 0) > data.get("sets_a", 0):
            data["vainqueur"] = data.get("equipe_b")

        return data

    def get_scores_for_entity(
        self,
        entity_code: str,
        saison: str,
        poule_codes: Optional[list[str]] = None,
    ) -> list[OnlineMatchScore]:
        """
        Récupère les scores de toutes les poules d'une entité.

        Args:
            entity_code: Code de l'entité
            saison: Saison au format YYYY/YYYY
            poule_codes: Liste de codes de poules spécifiques (optionnel)

        Returns:
            Liste complète des scores trouvés en ligne.
        """
        if poule_codes is None:
            poules = self._scraper.get_poules_for_entity(entity_code, saison)
            poule_codes = [p.code for p in poules]

        all_scores: list[OnlineMatchScore] = []
        for pc in poule_codes:
            try:
                scores = self.get_scores_for_poule(entity_code, pc, saison)
                all_scores.extend(scores)
            except Exception as e:
                logger.warning(
                    "Erreur lors de la récupération des scores %s/%s %s : %s",
                    entity_code, pc, saison, e,
                )
        return all_scores
