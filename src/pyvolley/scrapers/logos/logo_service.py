"""Service unifié de recherche et synchronisation des logos de clubs.

Combine :
1. Volleybox (catalogue local de ~800 clubs français avec logos officiels),
2. Wikipedia / Wikimedia Commons (logos vectoriels SVG et HD pour clubs pro/nationaux),
3. SvgBadgeGenerator (génération vectorielle élégante pour clubs amateurs sans logo).
"""

from __future__ import annotations

from dataclasses import dataclass, field
import logging
from pathlib import Path
from typing import Any, Optional

from pyvolley.scrapers.logos.svg_badge_generator import SvgBadgeGenerator
from pyvolley.scrapers.logos.wikipedia_provider import WikipediaLogoProvider
from pyvolley.scrapers.volleybox.logo_scraper import LogoCandidate, VolleyboxLogoScraper

logger = logging.getLogger(__name__)


@dataclass
class ClubLogoResult:
    """Résultat unifié pour un logo de club."""

    logo_url: str
    source: str  # 'volleybox', 'wikipedia', 'generated_badge'
    confidence: float
    matched_name: Optional[str] = None
    reference_url: Optional[str] = None
    is_fallback: bool = False
    details: dict[str, Any] = field(default_factory=dict)


class ClubLogoService:
    """Orchestrateur multi-sources pour la résolution des logos de clubs."""

    def __init__(
        self,
        volleybox_scraper: Optional[VolleyboxLogoScraper] = None,
        wikipedia_provider: Optional[WikipediaLogoProvider] = None,
        cache_path: Optional[Path | str] = None,
    ) -> None:
        self.volleybox = volleybox_scraper or VolleyboxLogoScraper(
            cache_path=cache_path,
        )
        self.wikipedia = wikipedia_provider or WikipediaLogoProvider()
        self.badge_generator = SvgBadgeGenerator()

    def refresh_catalog(self) -> int:
        """Actualise le catalogue local Volleybox depuis le web."""
        return self.volleybox.refresh_catalog()

    def get_catalog_stats(self) -> dict[str, Any]:
        """Retourne les statistiques du catalogue Volleybox en cache."""
        cache_file = self.volleybox.cache_path
        exists = cache_file.exists()
        count = 0
        with_logo = 0
        if exists:
            try:
                entries = self.volleybox._load_from_cache() or []
                count = len(entries)
                with_logo = sum(1 for e in entries if e.logo_url)
            except Exception:
                pass

        return {
            "cache_path": str(cache_file),
            "cached": exists,
            "total_clubs": count,
            "clubs_with_logo": with_logo,
        }

    def resolve_logo(
        self,
        nom: str,
        nom_court: Optional[str] = None,
        ville: Optional[str] = None,
        departement: Optional[str] = None,
        couleurs: Optional[str] = None,
        aliases: Optional[list[str]] = None,
        *,
        min_score: float = 0.60,
        enable_wikipedia: bool = True,
        enable_volleybox: bool = True,
        enable_badge_fallback: bool = False,
        prefer_wikipedia: bool = False,
    ) -> Optional[ClubLogoResult]:
        """Recherche le meilleur logo disponible pour un club.

        Args:
            nom: Nom officiel du club (ex: 'ASUL LYON VOLLEY BALL').
            nom_court: Nom court optionnel (ex: 'ASUL LYON').
            ville: Ville d'attachement (ex: 'LYON').
            departement: Code département (ex: '69').
            couleurs: Chaîne des couleurs officielles FFVB (ex: 'Rouge / Noir').
            aliases: Variantes ou alias connus.
            min_score: Score minimal de matching requis (0.0 à 1.0).
            enable_wikipedia: Activer la recherche Wikipédia.
            enable_volleybox: Activer la recherche Volleybox.
            enable_badge_fallback: Générer un blason SVG si aucun logo trouvé.
            prefer_wikipedia: Tenter Wikipédia en priorité.

        Returns:
            ClubLogoResult si trouvé, sinon None.
        """
        raw_names = [nom]
        if nom_court:
            raw_names.append(nom_court)
        if aliases:
            raw_names.extend(aliases)

        # Déduplication et nettoyage des noms
        ordered_names: list[str] = []
        seen_names: set[str] = set()
        for name in raw_names:
            clean = (name or "").strip()
            if not clean:
                continue
            key = clean.lower()
            if key in seen_names:
                continue
            seen_names.add(key)
            ordered_names.append(clean)

        if not ordered_names:
            return None

        # 1. Option : Priorité Wikipedia
        if prefer_wikipedia and enable_wikipedia:
            wiki_res = self.wikipedia.find_logo(ordered_names[0], city=ville)
            if wiki_res:
                return ClubLogoResult(
                    logo_url=wiki_res.logo_url,
                    source="wikipedia",
                    confidence=wiki_res.score,
                    matched_name=wiki_res.page_title,
                    reference_url=f"https://fr.wikipedia.org/wiki/{wiki_res.page_title}",
                    details={"file": wiki_res.file_name},
                )

        # 2. Tier 1 : Volleybox (Catalogue complet & matching fin)
        if enable_volleybox:
            vb_candidate = self.volleybox.find_logo_for_club(
                ordered_names,
                target_city=ville,
                prefer_google=False,  # Pas de scraping bloquant
            )
            if vb_candidate and vb_candidate.logo_url and vb_candidate.score >= min_score:
                return ClubLogoResult(
                    logo_url=vb_candidate.logo_url,
                    source="volleybox",
                    confidence=vb_candidate.score,
                    matched_name=vb_candidate.matched_name,
                    reference_url=vb_candidate.result_url or vb_candidate.team_url,
                    details={
                        "slug": vb_candidate.slug,
                        "city": vb_candidate.matched_city,
                        "city_score": vb_candidate.city_score,
                    },
                )

        # 3. Tier 2 : Wikipedia (si non trouvé sur Volleybox ou score insuffisant)
        if enable_wikipedia and not prefer_wikipedia:
            wiki_res = self.wikipedia.find_logo(ordered_names[0], city=ville)
            if wiki_res:
                return ClubLogoResult(
                    logo_url=wiki_res.logo_url,
                    source="wikipedia",
                    confidence=wiki_res.score,
                    matched_name=wiki_res.page_title,
                    reference_url=f"https://fr.wikipedia.org/wiki/{wiki_res.page_title}",
                    details={"file": wiki_res.file_name},
                )

        # 4. Tier 3 : Fallback Blason SVG généré (si activé)
        if enable_badge_fallback:
            badge_data_uri = self.badge_generator.generate_data_uri(
                club_name=ordered_names[0],
                couleurs=couleurs,
                city=ville,
            )
            return ClubLogoResult(
                logo_url=badge_data_uri,
                source="generated_badge",
                confidence=0.50,
                matched_name=ordered_names[0],
                is_fallback=True,
                details={"couleurs": couleurs, "type": "svg_data_uri"},
            )

        return None
