"""
Scraper de scores en ligne pour compléter les données manquantes.

Récupère les résultats (score en sets, scores détaillés par set, date,
arbitres, etc.) depuis les pages de calendrier du site FFVB (ffvbbeach.org).

Le calendrier FFVB structure les données de match en cellules séquentielles
dans un grand tableau HTML. Chaque match suit le pattern :

  [code, date, heure, equipeA, '', equipeB, setsA, setsB, scores, total, arbitres, '']

Ce module parse ce flux structuré pour extraire toutes les informations
disponibles.

Utilisation typique :
  1. Le parser PDF extrait un match sans détails (feuille pré-2024).
  2. Ce module récupère les scores depuis le calendrier en ligne.
  3. L'import service met à jour le match en DB avec ``score_source="online"``.
"""

import logging
import re
from dataclasses import dataclass
from typing import Optional

from pyvolley.scrapers.ffvb import FFVBScraper
from pyvolley.scrapers.ffvb.utils import build_calendar_url

logger = logging.getLogger(__name__)

# Regex pour détecter un code de match FFVB (ex: EMA001, 3FE003, PMA012)
_CODE_MATCH_RE = re.compile(r'^[A-Z0-9]{2,6}\d{3,4}$', re.I)

# Regex pour détecter une date au format DD/MM/YY ou DD/MM/YYYY
_DATE_RE = re.compile(r'^\d{2}/\d{2}/\d{2,4}$')

# Regex pour détecter une heure au format HH:MM
_TIME_RE = re.compile(r'^\d{1,2}:\d{2}$')

# Regex pour détecter un score de set (ex: 25:20, 25-20)
_SET_SCORE_RE = re.compile(r'(\d{1,2})\s*[:]\s*(\d{1,2})')

# Regex pour un score total (ex: 075-047, 100-098)
_TOTAL_SCORE_RE = re.compile(r'^(\d{3})-(\d{3})$')

# Regex pour une ligne "Journée XX"
_JOURNEE_RE = re.compile(r'^Journée\s+(\d+)', re.I)

# Valeurs de sets spéciales (forfait, pénalité)
_FORFAIT_MARKERS = frozenset({'P', 'F'})


@dataclass
class OnlineMatchScore:
    """Score d'un match récupéré en ligne depuis le calendrier FFVB."""
    code_match: str
    entity_code: str
    poule_code: str
    saison: str

    # Équipes
    equipe_a: Optional[str] = None
    equipe_b: Optional[str] = None

    # Résultat en sets
    score_sets: Optional[str] = None   # "3/1"
    sets_a: int = 0
    sets_b: int = 0

    # Scores détaillés par set : [(25, 20), (22, 25), ...]
    set_scores: Optional[list[tuple[int, int]]] = None

    # Informations supplémentaires
    vainqueur: Optional[str] = None
    date: Optional[str] = None          # "28/09/24"
    heure: Optional[str] = None         # "20:00"
    journee: Optional[str] = None       # "01"
    arbitres: Optional[str] = None      # "NOM1 PRENOM1/NOM2 PRENOM2"
    arbitre_1: Optional[str] = None     # Premier arbitre
    arbitre_2: Optional[str] = None     # Second arbitre
    total_points_a: Optional[int] = None  # Total des points marqués par A
    total_points_b: Optional[int] = None  # Total des points marqués par B

    # Flags
    is_forfait: bool = False     # Match gagné par forfait
    is_exempt: bool = False      # Équipe exemptée (adversaire = xxxxx)
    is_reporte: bool = False     # Match reporté
    match_joue: bool = False     # Match effectivement joué

    def __post_init__(self):
        if self.set_scores is None:
            self.set_scores = []

    @property
    def is_complete(self) -> bool:
        """True si les scores sont présents et cohérents."""
        if self.is_exempt or self.is_reporte:
            return False
        if self.is_forfait:
            return self.sets_a + self.sets_b > 0
        return (
            self.sets_a + self.sets_b > 0
            and self.set_scores is not None
            and len(self.set_scores) == self.sets_a + self.sets_b
        )

    @property
    def has_result(self) -> bool:
        """True si le match a un résultat (joué ou forfait)."""
        return self.match_joue or self.is_forfait

    @property
    def arbitres_list(self) -> list[str]:
        """Liste des noms d'arbitres."""
        parts = []
        if self.arbitre_1:
            parts.append(self.arbitre_1)
        if self.arbitre_2:
            parts.append(self.arbitre_2)
        return parts


class FFVBScoreScraper:
    """
    Scrape les scores de matchs depuis les pages de calendrier FFVB.

    Le calendrier contient :
    - Les noms des équipes
    - Le score en sets (ex: 3-1) avec les marqueurs spéciaux (P, F)
    - Les scores détaillés par set (ex: 25:20, 22:25, 25:18, 25:15)
    - La date et l'heure du match
    - Les noms des arbitres
    - Le total de points par équipe

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
        url = build_calendar_url(
            self._scraper.base_url,
            entity_code,
            saison,
            poule=poule_code,
        )

        try:
            soup = self._scraper.client.get_soup(url)
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

        La page contient un grand tableau dont les cellules suivent une
        structure séquentielle. On parcourt le flux de cellules aplati
        pour identifier les segments de match.

        Structure d'un segment de match joué :
          [code, date, heure, equipeA, '', equipeB, setsA, setsB,
           scores_détaillés, total_points, arbitres, '']

        Segment exempt (adversaire = xxxxx) :
          [code, date, heure, equipe, '', 'xxxxx', '', '', '', '']
        """
        scores: list[OnlineMatchScore] = []
        seen: set[str] = set()

        # Aplatir toutes les cellules de tous les tableaux
        all_cells: list[str] = []
        for table in soup.find_all("table"):
            for row in table.find_all("tr"):
                for cell in row.find_all(["td", "th"]):
                    all_cells.append(cell.get_text(strip=True))

        if not all_cells:
            return scores

        # Parcourir le flux de cellules pour trouver les segments de match
        current_journee: Optional[str] = None
        i = 0

        while i < len(all_cells):
            text = all_cells[i]

            # Détecter les marqueurs de journée
            jm = _JOURNEE_RE.match(text)
            if jm:
                current_journee = jm.group(1).zfill(2)
                i += 1
                continue

            # Détecter un code de match
            if _CODE_MATCH_RE.match(text):
                code_match = text.upper()

                # Protéger contre les doublons (le code peut apparaître dans
                # le classement ou dans les liens)
                if code_match in seen:
                    i += 1
                    continue

                # Essayer de parser le segment de match
                oms, consumed = self._parse_match_segment(
                    all_cells, i, entity_code, poule_code, saison,
                    current_journee,
                )

                if oms is not None:
                    seen.add(code_match)
                    scores.append(oms)
                    i += consumed
                else:
                    i += 1
            else:
                i += 1

        logger.info(
            "Calendrier %s/%s %s : %d scores récupérés (%d joués, %d forfaits, "
            "%d exempts)",
            entity_code, poule_code, saison, len(scores),
            sum(1 for s in scores if s.match_joue and not s.is_forfait),
            sum(1 for s in scores if s.is_forfait),
            sum(1 for s in scores if s.is_exempt),
        )
        return scores

    @staticmethod
    def _parse_match_segment(
        cells: list[str],
        start: int,
        entity_code: str,
        poule_code: str,
        saison: str,
        journee: Optional[str],
    ) -> tuple[Optional['OnlineMatchScore'], int]:
        """Parse un segment de match depuis une position dans le flux de cellules.

        Returns:
            Tuple (OnlineMatchScore ou None, nombre de cellules consommées).
        """
        n = len(cells)

        # Minimum : code + date + heure + equipeA + '' + equipeB = 6 cellules
        if start + 5 >= n:
            return None, 1

        code_match = cells[start].upper()

        # Vérifier que les cellules suivantes sont bien date + heure
        # (protection contre les faux codes dans le classement)
        pos = start + 1
        date_str = None
        heure_str = None

        # Chercher date (immédiatement après le code en général)
        if pos < n and _DATE_RE.match(cells[pos]):
            date_str = cells[pos]
            pos += 1
        else:
            # Pas une vraie ligne de match
            return None, 1

        # Chercher heure
        if pos < n and _TIME_RE.match(cells[pos]):
            heure_str = cells[pos]
            pos += 1

        # Équipe A (le prochain texte non vide)
        equipe_a = None
        if pos < n:
            equipe_a = cells[pos]
            pos += 1

        # Séparateur vide entre les deux équipes
        if pos < n and cells[pos] == '':
            pos += 1

        # Équipe B (ou 'xxxxx' pour exemption)
        equipe_b = None
        if pos < n:
            equipe_b = cells[pos]
            pos += 1

        # Vérifier l'exemption
        is_exempt = equipe_b is not None and 'xxxxx' in equipe_b.lower()

        if is_exempt:
            # Pour un match exempt, on saute les cellules vides restantes
            while pos < n and cells[pos] == '':
                pos += 1
                if pos - start > 12:
                    break
            return OnlineMatchScore(
                code_match=code_match,
                entity_code=entity_code,
                poule_code=poule_code,
                saison=saison,
                equipe_a=equipe_a,
                equipe_b=None,
                date=date_str,
                heure=heure_str,
                journee=journee,
                is_exempt=True,
                match_joue=False,
            ), pos - start

        # Pour les matchs joués : chercher les sets
        sets_a = 0
        sets_b = 0
        is_forfait = False
        sets_text_a = None
        sets_text_b = None

        # Sets A
        if pos < n:
            sa = cells[pos]
            if sa.isdigit() and 0 <= int(sa) <= 3:
                sets_a = int(sa)
                sets_text_a = sa
                pos += 1
            elif sa.upper() in _FORFAIT_MARKERS:
                # Forfait côté A: P ou F
                is_forfait = True
                sets_text_a = sa.upper()
                pos += 1
            elif sa == '':
                # Match non encore joué
                # Consommer les cellules vides restantes du segment
                while pos < n and cells[pos] == '':
                    pos += 1
                    if pos - start > 12:
                        break
                return OnlineMatchScore(
                    code_match=code_match,
                    entity_code=entity_code,
                    poule_code=poule_code,
                    saison=saison,
                    equipe_a=equipe_a,
                    equipe_b=equipe_b,
                    date=date_str,
                    heure=heure_str,
                    journee=journee,
                    match_joue=False,
                ), pos - start
            else:
                # Pas de score reconnu - match probablement non joué
                return OnlineMatchScore(
                    code_match=code_match,
                    entity_code=entity_code,
                    poule_code=poule_code,
                    saison=saison,
                    equipe_a=equipe_a,
                    equipe_b=equipe_b,
                    date=date_str,
                    heure=heure_str,
                    journee=journee,
                    match_joue=False,
                ), pos - start

        # Sets B
        if pos < n:
            sb = cells[pos]
            if sb.isdigit() and 0 <= int(sb) <= 3:
                sets_b = int(sb)
                sets_text_b = sb
                pos += 1
            elif sb.upper() in _FORFAIT_MARKERS:
                is_forfait = True
                sets_text_b = sb.upper()
                pos += 1
            elif sb == '':
                # Pas de score sets B → match non joué
                pass
            else:
                pos += 1

        # Construire le score en sets
        score_sets = None
        if sets_a + sets_b > 0 or is_forfait:
            score_sets = f"{sets_a}/{sets_b}"

        # Scores détaillés par set (ex: "25:20, 25:11, 25:16")
        set_scores: list[tuple[int, int]] = []
        if pos < n and cells[pos]:
            detail = cells[pos]
            for m in _SET_SCORE_RE.finditer(detail):
                a, b = int(m.group(1)), int(m.group(2))
                set_scores.append((a, b))
            if set_scores:
                pos += 1
            elif detail == '':
                pos += 1

        # Total des points (ex: "075-047")
        total_pts_a: Optional[int] = None
        total_pts_b: Optional[int] = None
        if pos < n:
            tm = _TOTAL_SCORE_RE.match(cells[pos])
            if tm:
                total_pts_a = int(tm.group(1))
                total_pts_b = int(tm.group(2))
                pos += 1

        # Arbitres (ex: "NOM1 PRENOM1/NOM2 PRENOM2")
        arbitres_str: Optional[str] = None
        arbitre_1: Optional[str] = None
        arbitre_2: Optional[str] = None
        if pos < n and cells[pos]:
            candidate = cells[pos]
            # Un nom d'arbitre contient un "/" séparateur et pas de score
            if '/' in candidate and not _TOTAL_SCORE_RE.match(candidate):
                # Vérifier que ça ressemble à des noms (pas un score)
                parts = candidate.split('/')
                if len(parts) == 2 and all(
                    len(p.strip()) > 2 and not p.strip().isdigit()
                    for p in parts
                ):
                    arbitres_str = candidate
                    arbitre_1 = parts[0].strip()
                    arbitre_2 = parts[1].strip()
                    pos += 1

        # Séparateur vide de fin
        if pos < n and cells[pos] == '':
            pos += 1

        # Déterminer le match joué
        match_joue = (sets_a + sets_b > 0) or is_forfait

        # Déterminer le vainqueur
        vainqueur = None
        if is_forfait:
            if sets_text_a in _FORFAIT_MARKERS:
                # A a forfait → B gagne
                sets_a = 0
                vainqueur = equipe_b
            elif sets_text_b in _FORFAIT_MARKERS:
                # B a forfait → A gagne
                sets_b = 0
                vainqueur = equipe_a
            score_sets = f"{sets_a}/{sets_b}"
        elif sets_a > sets_b and match_joue:
            vainqueur = equipe_a
        elif sets_b > sets_a and match_joue:
            vainqueur = equipe_b

        return OnlineMatchScore(
            code_match=code_match,
            entity_code=entity_code,
            poule_code=poule_code,
            saison=saison,
            equipe_a=equipe_a,
            equipe_b=equipe_b,
            score_sets=score_sets,
            sets_a=sets_a,
            sets_b=sets_b,
            set_scores=set_scores if set_scores else [],
            vainqueur=vainqueur,
            date=date_str,
            heure=heure_str,
            journee=journee,
            arbitres=arbitres_str,
            arbitre_1=arbitre_1,
            arbitre_2=arbitre_2,
            total_points_a=total_pts_a,
            total_points_b=total_pts_b,
            is_forfait=is_forfait,
            match_joue=match_joue,
        ), pos - start

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

    def get_match_score(
        self,
        code_match: str,
        entity_code: str,
        poule_code: str,
        saison: str,
    ) -> Optional[OnlineMatchScore]:
        """
        Récupère le score d'un match spécifique.

        Args:
            code_match: Code du match (ex: "EMA001")
            entity_code: Code de l'entité
            poule_code: Code de la poule
            saison: Saison au format YYYY/YYYY

        Returns:
            OnlineMatchScore si trouvé, None sinon.
        """
        scores = self.get_scores_for_poule(entity_code, poule_code, saison)
        for s in scores:
            if s.code_match == code_match.upper():
                return s
        return None

    def get_summary(
        self,
        entity_code: str,
        poule_code: str,
        saison: str,
    ) -> dict:
        """
        Résumé statistique des données disponibles pour une poule.

        Returns:
            Dictionnaire avec les statistiques de la poule.
        """
        scores = self.get_scores_for_poule(entity_code, poule_code, saison)
        total = len(scores)
        played = sum(1 for s in scores if s.match_joue)
        forfeits = sum(1 for s in scores if s.is_forfait)
        exempts = sum(1 for s in scores if s.is_exempt)
        complete = sum(1 for s in scores if s.is_complete)
        with_arbitres = sum(1 for s in scores if s.arbitres)
        with_date = sum(1 for s in scores if s.date)
        with_set_scores = sum(
            1 for s in scores if s.set_scores and len(s.set_scores) > 0
        )
        not_played = total - played - exempts

        teams: set[str] = set()
        for s in scores:
            if s.equipe_a:
                teams.add(s.equipe_a)
            if s.equipe_b:
                teams.add(s.equipe_b)

        return {
            "entity_code": entity_code,
            "poule_code": poule_code,
            "saison": saison,
            "total_matches": total,
            "played": played,
            "forfeits": forfeits,
            "exempts": exempts,
            "not_played": not_played,
            "complete_scores": complete,
            "with_set_scores": with_set_scores,
            "with_arbitres": with_arbitres,
            "with_date": with_date,
            "teams": sorted(teams),
            "completion_pct": round(
                complete / (total - exempts) * 100, 1
            ) if total - exempts > 0 else 0.0,
        }
