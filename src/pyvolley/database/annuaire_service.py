"""
Service de synchronisation et d'enrichissement de l'annuaire fédéral officiel (FFVB).

Gère la persistance des Ligues (LigueDB), Comités (ComiteDB) et Clubs (ClubDB)
ainsi que la géolocalisation haute précision basée sur le siège social.
"""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Callable, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from pyvolley.core.geocoding import geocode_addresses_batch
from pyvolley.core.geo_data import DEPT_TO_LIGUE, department_from_club_code
from pyvolley.database.models import ClubDB, ComiteDB, LigueDB
from pyvolley.scrapers.ffvb.annuaire_scraper import (
    AnnuaireClubInfo,
    AnnuaireFicheClub,
    AnnuaireScraper,
)

logger = logging.getLogger(__name__)


class AnnuaireService:
    """Service de synchronisation de l'annuaire fédéral FFVB."""

    def __init__(self, session: Session, scraper: Optional[AnnuaireScraper] = None):
        self.session = session
        self.scraper = scraper or AnnuaireScraper()

    def sync_annuaire(
        self,
        geocode: bool = True,
        fetch_details: bool = True,
        force_refresh: bool = False,
        max_workers: int = 10,
        progress_callback: Optional[Callable[[str, int, int], None]] = None,
    ) -> dict:
        """Moissonne et synchronise l'intégralité du référentiel fédéral.

        Args:
            geocode: Géocoder par lot les sièges sociaux des clubs (défaut: True).
            fetch_details: Récupérer les fiches détaillées (adresses de siège, dirigeants)
                           (défaut: True).
            force_refresh: Forcer le re-téléchargement sans utiliser le cache disque.
            max_workers: Nombre de threads concurrents.
            progress_callback: Callback facultatif (étape, act, total).

        Returns:
            Dictionnaire de métriques de synchronisation.
        """
        stats = {
            "ligues_synced": 0,
            "comites_synced": 0,
            "clubs_created": 0,
            "clubs_updated": 0,
            "clubs_geocoded": 0,
        }

        # ── 1. Scraping des ligues, comités et clubs de base ─────────────────
        if progress_callback:
            progress_callback("Moissonnage des ligues et comités régionaux...", 0, 23)

        raw_ligues, raw_comites, raw_clubs = self.scraper.scrape_all_ligues(
            force_refresh=force_refresh, max_workers=max_workers
        )

        # ── 2. Scraping approfondi des fiches clubs (sièges sociaux) ─────────
        fiches_by_code: dict[str, AnnuaireFicheClub] = {}
        if fetch_details and raw_clubs:
            total_c = len(raw_clubs)
            if progress_callback:
                progress_callback("Récupération des adresses de sièges sociaux...", 0, total_c)

            done_c = 0
            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                future_to_code = {
                    executor.submit(
                        self.scraper.fetch_club_fiche, c.code_ffvb, force_refresh=force_refresh
                    ): c.code_ffvb
                    for c in raw_clubs
                }
                for future in as_completed(future_to_code):
                    code = future_to_code[future]
                    try:
                        fiche = future.result()
                        fiches_by_code[code] = fiche
                    except Exception as e:
                        logger.debug("Erreur récupération fiche club %s: %s", code, e)
                    done_c += 1
                    if progress_callback and (done_c % 50 == 0 or done_c == total_c):
                        progress_callback(
                            f"Récupération sièges sociaux ({done_c}/{total_c})...",
                            done_c,
                            total_c,
                        )

        # ── 3. Persistance des Ligues (LigueDB) ──────────────────────────────
        existing_ligues = {l.code: l for l in self.session.scalars(select(LigueDB)).all()}
        ligue_db_map: dict[str, LigueDB] = {}

        for l_info in raw_ligues:
            ligue_obj = existing_ligues.get(l_info.code)
            if not ligue_obj:
                ligue_obj = LigueDB(
                    code=l_info.code,
                    nom=l_info.nom,
                    telephone=l_info.telephone,
                    email=l_info.email,
                    site_web=l_info.site_web,
                    adresse_siege=l_info.adresse_siege,
                    president=l_info.president,
                )
                self.session.add(ligue_obj)
            else:
                ligue_obj.nom = l_info.nom
                if l_info.telephone:
                    ligue_obj.telephone = l_info.telephone
                if l_info.email:
                    ligue_obj.email = l_info.email
                if l_info.site_web:
                    ligue_obj.site_web = l_info.site_web
                if l_info.president:
                    ligue_obj.president = l_info.president
                if l_info.adresse_siege:
                    ligue_obj.adresse_siege = l_info.adresse_siege

            ligue_db_map[l_info.code] = ligue_obj
            stats["ligues_synced"] += 1

        self.session.flush()

        # ── 4. Persistance des Comités Départementaux (ComiteDB) ─────────────
        existing_comites = {c.code: c for c in self.session.scalars(select(ComiteDB)).all()}
        comite_db_map: dict[str, ComiteDB] = {}

        for c_info in raw_comites:
            parent_ligue = ligue_db_map.get(c_info.ligue_code)
            comite_obj = existing_comites.get(c_info.code)
            if not comite_obj:
                comite_obj = ComiteDB(
                    code=c_info.code,
                    numero_departement=c_info.numero_departement,
                    nom=c_info.nom,
                    ligue_id=parent_ligue.id if parent_ligue else None,
                    telephone=c_info.telephone,
                    email=c_info.email,
                    site_web=c_info.site_web,
                    adresse_siege=c_info.adresse_siege,
                )
                self.session.add(comite_obj)
            else:
                comite_obj.nom = c_info.nom
                if c_info.numero_departement:
                    comite_obj.numero_departement = c_info.numero_departement
                if parent_ligue:
                    comite_obj.ligue_id = parent_ligue.id
                if c_info.telephone:
                    comite_obj.telephone = c_info.telephone
                if c_info.email:
                    comite_obj.email = c_info.email
                if c_info.site_web:
                    comite_obj.site_web = c_info.site_web
                if c_info.adresse_siege:
                    comite_obj.adresse_siege = c_info.adresse_siege

            comite_db_map[c_info.code] = comite_obj
            stats["comites_synced"] += 1

        self.session.flush()

        # ── 5. Persistance des Clubs (ClubDB) ────────────────────────────────
        all_codes = [c.code_ffvb for c in raw_clubs if c.code_ffvb]
        existing_clubs: dict[str, ClubDB] = {}
        if all_codes:
            for i in range(0, len(all_codes), 900):
                chunk = all_codes[i : i + 900]
                for c in self.session.scalars(
                    select(ClubDB).where(ClubDB.code_ffvb.in_(chunk))
                ).all():
                    existing_clubs[c.code_ffvb] = c

        clubs_to_geocode: list[ClubDB] = []

        for c_info in raw_clubs:
            parent_ligue = ligue_db_map.get(c_info.ligue_code)
            parent_comite = comite_db_map.get(c_info.comite_code)
            fiche = fiches_by_code.get(c_info.code_ffvb)

            club_obj = existing_clubs.get(c_info.code_ffvb)
            is_new = False
            if not club_obj:
                club_obj = ClubDB(
                    code_ffvb=c_info.code_ffvb,
                    nom=c_info.nom,
                )
                self.session.add(club_obj)
                existing_clubs[c_info.code_ffvb] = club_obj
                is_new = True
                stats["clubs_created"] += 1
            else:
                stats["clubs_updated"] += 1

            # Mettre à jour les champs de rattachement
            club_obj.nom = c_info.nom
            if parent_ligue:
                club_obj.ligue_id = parent_ligue.id
                club_obj.ligue = parent_ligue.nom
            if parent_comite:
                club_obj.comite_id = parent_comite.id
                club_obj.departement = parent_comite.numero_departement

            # Mettre à jour coordonnées de base
            if c_info.email:
                club_obj.email = c_info.email
            if c_info.site_web:
                club_obj.site_web = c_info.site_web

            # Enrichir depuis la fiche détaillée si disponible
            if fiche:
                if fiche.adresse_siege:
                    club_obj.adresse_siege = fiche.adresse_siege
                if fiche.code_postal_siege:
                    club_obj.code_postal_siege = fiche.code_postal_siege
                if fiche.ville_siege:
                    club_obj.ville_siege = fiche.ville_siege
                    if not club_obj.ville:
                        club_obj.ville = fiche.ville_siege
                if fiche.couleurs:
                    club_obj.couleurs = fiche.couleurs
                if fiche.president:
                    club_obj.president = fiche.president
                if fiche.correspondant_nom:
                    club_obj.correspondant_nom = fiche.correspondant_nom
                if fiche.telephone:
                    club_obj.telephone = fiche.telephone
                if fiche.portable and not club_obj.correspondant_portable:
                    club_obj.correspondant_portable = fiche.portable
                if fiche.email and not club_obj.correspondant_email:
                    club_obj.correspondant_email = fiche.email

            if geocode:
                clubs_to_geocode.append(club_obj)

        self.session.flush()

        # ── 6. Géocodage par Lot sur le Siège Social ─────────────────────────
        if geocode and clubs_to_geocode:
            total_geo = len(clubs_to_geocode)
            if progress_callback:
                progress_callback("Géocodage des sièges sociaux par batch BAN...", 0, total_geo)

            geo_items = []
            for c in clubs_to_geocode:
                # Priorité absolue au siège social :
                addr = c.adresse_siege or None
                city = None
                if c.code_postal_siege or c.ville_siege:
                    city = f"{c.code_postal_siege or ''} {c.ville_siege or ''}".strip()
                elif c.ville:
                    city = c.ville

                c_dept = (
                    c.departement
                    or (c.comite_rel.numero_departement if c.comite_rel else None)
                    or department_from_club_code(c.code_ffvb)
                )
                c_ligue = (
                    c.ligue
                    or (c.ligue_rel.nom if c.ligue_rel else None)
                    or (DEPT_TO_LIGUE.get(c_dept) if c_dept else None)
                )

                # Si le club n'a pas encore de latitude ou si nouvelle adresse :
                if addr or city:
                    geo_items.append({
                        "id": f"club_{c.code_ffvb}",
                        "adresse": addr,
                        "ville": city,
                        "nom": c.nom,
                        "departement": c_dept,
                        "ligue": c_ligue,
                    })

            if geo_items:
                geo_results = geocode_addresses_batch(
                    geo_items,
                    use_cache=True,
                    allow_nominatim=False,
                )

                club_by_geo_id = {f"club_{c.code_ffvb}": c for c in clubs_to_geocode}
                for geo_id, res in geo_results.items():
                    if res and res.latitude is not None and res.longitude is not None:
                        club = club_by_geo_id.get(geo_id)
                        if club:
                            club.latitude = res.latitude
                            club.longitude = res.longitude
                            stats["clubs_geocoded"] += 1

        self.session.commit()
        logger.info("Synchronisation annuaire terminée avec succès: %s", stats)
        return stats
