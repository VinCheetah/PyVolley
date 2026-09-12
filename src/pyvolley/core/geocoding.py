"""
Moteur de géocodage haute précision pour les salles et clubs de volleyball.

Utilise en priorité l'API Adresse officielle française (Base Adresse Nationale - BAN,
api-adresse.data.gouv.fr) qui offre une précision au numéro de voirie sans clé d'API.
Dispose d'une stratégie de repli en cascade (nettoyage des libellés FFVB, tolérance aux
erreurs de code postal, recherche par nom d'équipement sportif, repli Nominatim/OSM).
"""

from __future__ import annotations

import csv
import io
import json
import logging
import re
import time
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable, Optional

from pyvolley.core.config import settings

logger = logging.getLogger(__name__)

BAN_API_URL = "https://api-adresse.data.gouv.fr/search/"
NOMINATIM_API_URL = "https://nominatim.openstreetmap.org/search"
DEFAULT_USER_AGENT = "PyVolley/1.0 (https://github.com/VinCheetah/PyVolley)"


@dataclass
class GeocodingResult:
    """Résultat géocodé avec niveau de précision."""
    latitude: float
    longitude: float
    label: str
    score: float
    match_type: str  # "housenumber", "street", "locality", "municipality", "fallback"
    city: Optional[str] = None
    postcode: Optional[str] = None
    provider: str = "ban"


# ── Utilitaires de nettoyage et normalisation ───────────────────────

def extract_postal_and_city(ville_str: Optional[str]) -> tuple[Optional[str], Optional[str]]:
    """Extrait le code postal à 5 chiffres et le nom épuré de la commune.

    Exemples :
        "42480 LA FOUILLOUSE" -> ("42480", "LA FOUILLOUSE")
        "69110 STE FOY LES LYON" -> ("69110", "STE FOY LES LYON")
        "GRENOBLE" -> (None, "GRENOBLE")
    """
    if not ville_str:
        return None, None

    cleaned = ville_str.strip()
    m = re.search(r"\b(\d{5})\b", cleaned)
    if m:
        postcode = m.group(1)
        city_part = re.sub(r"\b\d{5}\b", "", cleaned).strip(" -_,")
        return postcode, city_part if city_part else None

    return None, cleaned if cleaned else None


def clean_street_address(addr: Optional[str]) -> Optional[str]:
    """Nettoie les adresses FFVB des bruits fréquents (mentions de salle, ZI, etc.).

    Exemples :
        "15 RUE PAUL LAPIE, PETITE SALLE 1" -> "15 RUE PAUL LAPIE"
        "ALLEE DE GEVE, ZI L'ARGENTIERE" -> "ALLEE DE GEVE"
        "9 IMP. GEORGES CLEMENCEAU," -> "9 IMP. GEORGES CLEMENCEAU"
    """
    if not addr:
        return None

    cleaned = addr.strip().rstrip(" ,;/")
    # Supprimer les mentions accessoires courantes dans l'adressier FFVB
    noise_patterns = [
        r",?\s*(?:PETITE\s+)?SALLE\s*\d*.*$",
        r",?\s*GRANDE\s+SALLE.*$",
        r",?\s*ZI\s+.*$",
        r",?\s*Z\.I\.\s+.*$",
        r",?\s*ZA\s+.*$",
        r",?\s*Z\.A\.\s+.*$",
        r",?\s*B[AÂ]TIMENT\s+[A-Z0-9].*$",
        r",?\s*B[AÂ]T\.\s+[A-Z0-9].*$",
        r",?\s*ESPACE\s+[A-Z\s]+,.*$",
    ]
    for pattern in noise_patterns:
        cleaned = re.sub(pattern, "", cleaned, flags=re.IGNORECASE).strip()

    # Remplacer les virgules finales ou multiples espaces
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" ,;/")
    return cleaned if cleaned else None


# ── Gestionnaire de Cache ──────────────────────────────────────────

class GeocodingCache:
    """Cache persistant des requêtes de géocodage sur disque."""

    def __init__(self, cache_file: Optional[Path] = None):
        if cache_file is None:
            cache_dir = settings.data_dir / "cache"
            cache_dir.mkdir(parents=True, exist_ok=True)
            cache_file = cache_dir / "geocoding_cache.json"

        self.cache_file = cache_file
        self._memory_cache: dict[str, dict] = {}
        self._load()

    def _make_key(self, query: str, postcode: Optional[str]) -> str:
        norm_q = re.sub(r"\s+", " ", query.lower().strip())
        pc = (postcode or "").strip()
        return f"{norm_q}##{pc}"

    def _load(self) -> None:
        if self.cache_file.exists():
            try:
                with open(self.cache_file, "r", encoding="utf-8") as f:
                    self._memory_cache = json.load(f)
            except Exception as e:
                logger.warning(f"Impossible de lire le cache de géocodage {self.cache_file}: {e}")
                self._memory_cache = {}

    def save(self) -> None:
        try:
            with open(self.cache_file, "w", encoding="utf-8") as f:
                json.dump(self._memory_cache, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.warning(f"Impossible de sauvegarder le cache de géocodage: {e}")

    def is_not_found(self, query: str, postcode: Optional[str]) -> bool:
        """Retourne True si l'adresse est déjà connue comme introuvable dans le cache."""
        key = self._make_key(query, postcode)
        data = self._memory_cache.get(key)
        return bool(data and data.get("_not_found"))

    def get(self, query: str, postcode: Optional[str]) -> Optional[GeocodingResult]:
        key = self._make_key(query, postcode)
        data = self._memory_cache.get(key)
        if data and not data.get("_not_found"):
            return GeocodingResult(**data)
        return None

    def set(self, query: str, postcode: Optional[str], result: Optional[GeocodingResult]) -> None:
        key = self._make_key(query, postcode)
        if result is None:
            self._memory_cache[key] = {"_not_found": True, "ts": time.time()}
        else:
            self._memory_cache[key] = asdict(result)

    def set_not_found(self, query: str, postcode: Optional[str]) -> None:
        """Enregistre un résultat négatif persistant (adresse introuvable)."""
        self.set(query, postcode, None)


_GLOBAL_CACHE: Optional[GeocodingCache] = None


def get_geocoding_cache() -> GeocodingCache:
    """Retourne l'instance singleton du cache de géocodage."""
    global _GLOBAL_CACHE
    if _GLOBAL_CACHE is None:
        _GLOBAL_CACHE = GeocodingCache()
    return _GLOBAL_CACHE


# ── Appel API BAN ──────────────────────────────────────────────────

def _call_ban_api(
    query: str,
    postcode: Optional[str] = None,
    city: Optional[str] = None,
    result_type: Optional[str] = None,
    timeout: float = 6.0,
) -> Optional[GeocodingResult]:
    """Interroge l'API Adresse officielle du gouvernement français."""
    if not query or not query.strip():
        return None

    params: dict[str, str | int] = {
        "q": query.strip(),
        "limit": 1,
    }
    if postcode and len(postcode) == 5 and postcode.isdigit():
        params["postcode"] = postcode
    if city:
        params["city"] = city
    if result_type:
        params["type"] = result_type

    url = f"{BAN_API_URL}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(
        url,
        headers={"User-Agent": DEFAULT_USER_AGENT, "Accept": "application/json"},
    )

    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            if response.status != 200:
                return None
            data = json.loads(response.read().decode("utf-8"))
            features = data.get("features", [])
            if not features:
                return None

            best = features[0]
            geom = best.get("geometry", {})
            coords = geom.get("coordinates", [])
            if len(coords) < 2:
                return None

            lng, lat = float(coords[0]), float(coords[1])
            props = best.get("properties", {})
            score = float(props.get("score", 0.0))
            m_type = props.get("type", "street")
            label = props.get("label", query)
            res_city = props.get("city")
            res_postcode = props.get("postcode")

            return GeocodingResult(
                latitude=lat,
                longitude=lng,
                label=label,
                score=score,
                match_type=m_type,
                city=res_city,
                postcode=res_postcode,
                provider="ban",
            )
    except Exception as e:
        logger.debug(f"Erreur appel BAN ({query}, {postcode}): {e}")

def _call_ban_csv_batch(
    rows: list[dict[str, str]],
    timeout: float = 15.0,
) -> dict[str, GeocodingResult]:
    """Interroge l'API CSV Batch de la Base Adresse Nationale pour géocoder un lot d'adresses.

    Args:
        rows: Liste de dicts contenant au moins 'id', 'q', et optionnellement 'postcode', 'city'.

    Returns:
        Dictionnaire {id: GeocodingResult} pour les adresses localisées.
    """
    if not rows:
        return {}

    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=["id", "q", "postcode", "city"])
    writer.writeheader()
    for r in rows:
        writer.writerow({
            "id": str(r.get("id", "")),
            "q": str(r.get("q", "")),
            "postcode": str(r.get("postcode", "") or ""),
            "city": str(r.get("city", "") or ""),
        })

    csv_bytes = output.getvalue().encode("utf-8")
    url = f"{BAN_API_URL}csv/"

    try:
        import requests
        response = requests.post(
            url,
            files={"data": ("adresses.csv", csv_bytes, "text/csv")},
            data={"postcode": "postcode", "city": "city"},
            headers={"User-Agent": DEFAULT_USER_AGENT},
            timeout=timeout,
        )
        if response.status_code != 200:
            logger.debug("Échec BAN batch CSV (status=%d)", response.status_code)
            return {}

        results: dict[str, GeocodingResult] = {}
        reader = csv.DictReader(io.StringIO(response.text))
        for row in reader:
            item_id = row.get("id")
            lat_str = row.get("latitude")
            lon_str = row.get("longitude")
            score_str = row.get("result_score")
            if not item_id or not lat_str or not lon_str:
                continue

            try:
                lat = float(lat_str)
                lon = float(lon_str)
                score = float(score_str) if score_str else 0.5
            except ValueError:
                continue

            if score < 0.45:
                continue

            results[item_id] = GeocodingResult(
                latitude=lat,
                longitude=lon,
                label=row.get("result_label") or row.get("q") or "",
                score=score,
                match_type=row.get("result_type") or "street",
                city=row.get("result_city") or row.get("city"),
                postcode=row.get("result_postcode") or row.get("postcode"),
                provider="ban_batch",
            )
        return results
    except Exception as e:
        logger.debug("Exception lors de l'appel BAN batch CSV: %s", e)
        return {}


def _call_nominatim_api(
    query: str,
    timeout: float = 3.0,
) -> Optional[GeocodingResult]:
    """Repli vers Nominatim (OpenStreetMap) pour adresses spécifiques."""
    if not query or not query.strip():
        return None

    params = {
        "q": query.strip(),
        "format": "json",
        "limit": 1,
        "countrycodes": "fr,mc",
    }
    url = f"{NOMINATIM_API_URL}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(
        url,
        headers={"User-Agent": DEFAULT_USER_AGENT, "Accept": "application/json"},
    )

    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            if response.status != 200:
                return None
            data = json.loads(response.read().decode("utf-8"))
            if not data or not isinstance(data, list):
                return None

            best = data[0]
            lat = float(best["lat"])
            lng = float(best["lon"])
            label = best.get("display_name", query)
            m_type = best.get("type", "fallback")

            return GeocodingResult(
                latitude=lat,
                longitude=lng,
                label=label,
                score=0.7,
                match_type=m_type,
                provider="nominatim",
            )
    except Exception as e:
        logger.debug(f"Erreur appel Nominatim ({query}): {e}")
        return None


# ── Stratégie de Résolution en Cascade ──────────────────────────────

def geocode_address(
    adresse: Optional[str],
    ville: Optional[str],
    nom: Optional[str] = None,
    use_cache: bool = True,
    allow_nominatim: bool = False,
) -> Optional[GeocodingResult]:
    """Résout les coordonnées GPS précises d'une adresse avec stratégie de repli.

    Ordre de priorité de la cascade :
    1. Cache local (y compris résultats négatifs connus)
    2. BAN avec adresse nettoyée + code postal + commune
    3. BAN avec adresse nettoyée + commune (SANS code postal, corrige les CP erronés)
    4. BAN avec adresse brute + commune
    5. BAN avec nom de l'équipement sportif + commune (ex: "Gymnase Chatrousse Chamalières")
    6. Repli Nominatim OpenStreetMap (si allow_nominatim=True)
    7. BAN sur la commune seule (dernier recours pour positionner au moins sur la commune)
    """
    postcode, city_name = extract_postal_and_city(ville)
    clean_addr = clean_address_address = clean_street_address(adresse)

    cache = get_geocoding_cache() if use_cache else None

    # 1. Vérification dans le cache
    cache_key_addr = clean_addr or adresse or (nom or "")
    cache_q = f"{cache_key_addr} {city_name or ''}".strip()
    if cache:
        if cache.is_not_found(cache_q, postcode):
            return None
        cached = cache.get(cache_q, postcode)
        if cached:
            return cached

    result: Optional[GeocodingResult] = None

    # 2. BAN avec adresse nettoyée + code postal
    if clean_addr:
        q = f"{clean_addr} {city_name or ''}".strip()
        result = _call_ban_api(query=q, postcode=postcode)
        if result and result.score >= 0.5:
            if cache:
                cache.set(cache_q, postcode, result)
            return result

    # 3. BAN SANS code postal (rattrape les codes postaux erronés comme Chamalières ou Saint-Fons)
    if clean_addr and city_name:
        q = f"{clean_addr} {city_name}".strip()
        result = _call_ban_api(query=q, postcode=None)
        if result and result.score >= 0.5:
            if cache:
                cache.set(cache_q, postcode, result)
            return result

    # 4. BAN avec adresse brute
    if adresse and adresse != clean_addr:
        q = f"{adresse} {city_name or ''}".strip()
        result = _call_ban_api(query=q, postcode=None)
        if result and result.score >= 0.5:
            if cache:
                cache.set(cache_q, postcode, result)
            return result

    # 5. BAN avec nom de la salle + commune (ex: "GYMNASE CLEMENCEAU SAINT-ETIENNE")
    if nom and city_name:
        clean_nom = re.sub(r"^(?:GM\d+\s*-\s*|SALLE\s*\d*\s*-\s*)", "", nom.strip(), flags=re.IGNORECASE)
        q = f"{clean_nom} {city_name}".strip()
        result = _call_ban_api(query=q, postcode=postcode)
        if result and result.score >= 0.45:
            if cache:
                cache.set(cache_q, postcode, result)
            return result

    # 6. Repli Nominatim (désactivé par défaut lors des imports pour éviter les timeouts et blocages)
    if allow_nominatim and (clean_addr or nom):
        target = clean_addr or nom
        q = f"{target}, {city_name or ''}, France".strip(" ,")
        result = _call_nominatim_api(query=q)
        if result:
            if cache:
                cache.set(cache_q, postcode, result)
            return result

    # 7. Dernier recours : centroïde de la commune via BAN
    if city_name:
        result = _call_ban_api(query=city_name, postcode=postcode, result_type="municipality")
        if result:
            result.match_type = "municipality"
            if cache:
                cache.set(cache_q, postcode, result)
            return result

    # Enregistrement de l'échec dans le cache pour ne plus retenter inutilement le réseau
    if cache:
        cache.set_not_found(cache_q, postcode)

    return None


def geocode_addresses_batch(
    items: list[dict],
    use_cache: bool = True,
    allow_nominatim: bool = False,
) -> dict[str, Optional[GeocodingResult]]:
    """Géocode un lot d'adresses de façon optimisée (cache -> BAN CSV batch -> repli unitaire).

    Args:
        items: Liste de dicts avec clés :
               - 'id': identifiant unique (ex: "club_0622126_salle_1")
               - 'adresse': adresse voirie optionnelle
               - 'ville': commune ou code postal + commune
               - 'nom': nom optionnel (équipement, club)
        use_cache: Si True, consulte et alimente le cache persistant.
        allow_nominatim: Si True, autorise le repli Nominatim lors du repli unitaire.

    Returns:
        Dict {id: GeocodingResult ou None}.
    """
    if not items:
        return {}

    cache = get_geocoding_cache() if use_cache else None
    results: dict[str, Optional[GeocodingResult]] = {}
    to_query: list[dict] = []
    item_map: dict[str, dict] = {}

    normalized_items: list[dict] = []
    for idx, raw_item in enumerate(items):
        if isinstance(raw_item, dict):
            item_id = str(raw_item.get("id", idx))
            normalized_items.append({
                "id": item_id,
                "adresse": raw_item.get("adresse"),
                "ville": raw_item.get("ville"),
                "nom": raw_item.get("nom"),
            })
        elif isinstance(raw_item, (tuple, list)):
            if len(raw_item) == 3:
                adresse, ville, nom = raw_item
                item_id = f"{adresse or ''}|{ville or ''}|{nom or ''}" or str(idx)
            elif len(raw_item) >= 4:
                item_id, adresse, ville, nom = raw_item[0], raw_item[1], raw_item[2], raw_item[3]
            else:
                adresse = raw_item[0] if len(raw_item) > 0 else None
                ville = raw_item[1] if len(raw_item) > 1 else None
                nom = None
                item_id = str(idx)
            normalized_items.append({
                "id": str(item_id),
                "adresse": adresse,
                "ville": ville,
                "nom": nom,
            })

    for item in normalized_items:
        item_id = item["id"]
        adresse = item.get("adresse")
        ville = item.get("ville")
        nom = item.get("nom")

        postcode, city_name = extract_postal_and_city(ville)
        clean_addr = clean_street_address(adresse)
        cache_key_addr = clean_addr or adresse or (nom or "")
        cache_q = f"{cache_key_addr} {city_name or ''}".strip()

        # 1. Vérification dans le cache (positif ou échec déjà connu)
        if cache:
            if cache.is_not_found(cache_q, postcode):
                results[item_id] = None
                continue
            cached = cache.get(cache_q, postcode)
            if cached:
                results[item_id] = cached
                continue

        # Préparer pour le batch
        item_map[item_id] = item
        if cache_q:
            to_query.append({
                "id": item_id,
                "q": cache_q,
                "postcode": postcode or "",
                "city": city_name or "",
            })
        else:
            results[item_id] = None

    # 2. Appel batch BAN pour les éléments manquants
    if to_query:
        batch_results = _call_ban_csv_batch(to_query)
        for item_id, res in batch_results.items():
            results[item_id] = res
            if cache and item_id in item_map:
                it = item_map[item_id]
                postcode, city_name = extract_postal_and_city(it.get("ville"))
                clean_addr = clean_street_address(it.get("adresse"))
                cache_key_addr = clean_addr or it.get("adresse") or (it.get("nom") or "")
                cache_q = f"{cache_key_addr} {city_name or ''}".strip()
                cache.set(cache_q, postcode, res)

    # 3. Repli unitaire pour les éléments non résolus par le batch
    for item in normalized_items:
        item_id = item["id"]
        if item_id not in results or results[item_id] is None:
            postcode, city_name = extract_postal_and_city(item.get("ville"))
            clean_addr = clean_street_address(item.get("adresse"))
            cache_key_addr = clean_addr or item.get("adresse") or (item.get("nom") or "")
            cache_q = f"{cache_key_addr} {city_name or ''}".strip()
            if cache and cache.is_not_found(cache_q, postcode):
                results[item_id] = None
                continue

            res = geocode_address(
                adresse=item.get("adresse"),
                ville=item.get("ville"),
                nom=item.get("nom"),
                use_cache=use_cache,
                allow_nominatim=allow_nominatim,
            )
            results[item_id] = res

    if cache:
        cache.save()

    return results


# ── Fonctions de Géocodage des Entités Base de Données ──────────────

def geocode_salle_entity(
    salle,
    *,
    session=None,
    force: bool = False,
    commit: bool = False,
) -> Optional[GeocodingResult]:
    """Géocode une instance de SalleClubDB et met à jour ses coordonnées.

    Args:
        salle: Instance SalleClubDB.
        session: Session SQLAlchemy optionnelle.
        force: Si True, ré-effectue le géocodage même si lat/lng déjà présents.
        commit: Si True et session fournie, exécute session.commit().

    Returns:
        GeocodingResult ou None.
    """
    if not force and salle.latitude is not None and salle.longitude is not None:
        return GeocodingResult(
            latitude=salle.latitude,
            longitude=salle.longitude,
            label=salle.adresse or salle.nom or "Existant",
            score=1.0,
            match_type="existing",
            city=salle.ville,
        )

    res = geocode_address(
        adresse=salle.adresse,
        ville=salle.ville or (salle.club.ville if getattr(salle, "club", None) else None),
        nom=salle.nom,
    )
    if res:
        salle.latitude = res.latitude
        salle.longitude = res.longitude
        if session and commit:
            session.commit()
    return res


def geocode_club_entity(
    club,
    *,
    session=None,
    force: bool = False,
    commit: bool = False,
) -> Optional[GeocodingResult]:
    """Positionne un ClubDB sur les coordonnées de sa salle principale (main venue).

    RÈGLE MÉTIER : On ne géocode JAMAIS l'adresse privée du correspondant.
    La position d'un club sur la carte correspond strictement à sa salle principale (Salle 1).
    En absence de salle déclarée, on se replie sur la commune du club (club.ville).
    """
    if not force and club.latitude is not None and club.longitude is not None:
        return GeocodingResult(
            latitude=club.latitude,
            longitude=club.longitude,
            label=club.nom or "Existant",
            score=1.0,
            match_type="existing",
            city=club.ville,
        )

    res: Optional[GeocodingResult] = None

    # 1. Priorité absolue : Salle principale du club (Salle 1 en priorité, sinon première salle)
    club_salles = getattr(club, "salles", None) or []
    main_salle = next((s for s in club_salles if s.numero == 1), None) or (club_salles[0] if club_salles else None)

    if main_salle:
        # S'assurer que la salle principale est géocodée
        if main_salle.latitude is None or main_salle.longitude is None or force:
            geocode_salle_entity(main_salle, session=session, force=force)

        if main_salle.latitude is not None and main_salle.longitude is not None:
            salle_nom = main_salle.nom or f"Salle {main_salle.numero}"
            res = GeocodingResult(
                latitude=main_salle.latitude,
                longitude=main_salle.longitude,
                label=f"{club.nom} ({salle_nom})",
                score=1.0,
                match_type="main_venue",
                city=main_salle.ville or club.ville,
                provider="venue",
            )

    # 2. Fallback uniquement sur la commune du club si aucune salle n'est déclarée (JAMAIS sur le correspondant)
    if not res and club.ville:
        res = geocode_address(
            adresse=None,
            ville=club.ville,
            nom=club.nom,
        )

    if res:
        club.latitude = res.latitude
        club.longitude = res.longitude
        if session and commit:
            session.commit()
    return res


# ── Traitement par Lot (Batch) ──────────────────────────────────────

def geocode_all_salles(
    session,
    *,
    force: bool = False,
    limit: int = 0,
    on_progress: Optional[Callable[[int, int, str], None]] = None,
) -> dict:
    """Géocode l'ensemble des salles_club en base.

    Returns:
        Dict des statistiques : total, geocoded, skipped, failed, housenumber, street, other.
    """
    from pyvolley.database.models import SalleClubDB

    query = session.query(SalleClubDB)
    if not force:
        query = query.filter((SalleClubDB.latitude.is_(None)) | (SalleClubDB.longitude.is_(None)))
    if limit > 0:
        query = query.limit(limit)

    salles = query.all()
    total = len(salles)
    stats = {
        "total": total,
        "geocoded": 0,
        "skipped": 0,
        "failed": 0,
        "housenumber": 0,
        "street": 0,
        "other": 0,
    }

    cache = get_geocoding_cache()

    for idx, salle in enumerate(salles, 1):
        nom_salle = salle.nom or f"Salle {salle.numero}"
        if on_progress:
            on_progress(idx, total, nom_salle)

        res = geocode_salle_entity(salle, session=session, force=force)
        if res:
            stats["geocoded"] += 1
            if res.match_type == "housenumber":
                stats["housenumber"] += 1
            elif res.match_type == "street":
                stats["street"] += 1
            else:
                stats["other"] += 1
        else:
            stats["failed"] += 1

        # Pause polie de 30ms pour préserver l'API
        time.sleep(0.03)

    session.commit()
    cache.save()
    return stats


def geocode_all_clubs(
    session,
    *,
    force: bool = False,
    limit: int = 0,
    on_progress: Optional[Callable[[int, int, str], None]] = None,
) -> dict:
    """Géocode l'ensemble des clubs en base."""
    from pyvolley.database.models import ClubDB

    query = session.query(ClubDB)
    if not force:
        query = query.filter((ClubDB.latitude.is_(None)) | (ClubDB.longitude.is_(None)))
    if limit > 0:
        query = query.limit(limit)

    clubs = query.all()
    total = len(clubs)
    stats = {
        "total": total,
        "geocoded": 0,
        "skipped": 0,
        "failed": 0,
        "housenumber": 0,
        "street": 0,
        "other": 0,
    }

    cache = get_geocoding_cache()

    for idx, club in enumerate(clubs, 1):
        if on_progress:
            on_progress(idx, total, club.nom)

        res = geocode_club_entity(club, session=session, force=force)
        if res:
            stats["geocoded"] += 1
            if res.match_type == "housenumber":
                stats["housenumber"] += 1
            elif res.match_type == "street":
                stats["street"] += 1
            else:
                stats["other"] += 1
        else:
            stats["failed"] += 1

        time.sleep(0.03)

    session.commit()
    cache.save()
    return stats
