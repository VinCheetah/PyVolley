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
from pyvolley.core.geo_data import (
    CITY_COORDINATES,
    DEPARTMENT_CENTROIDS,
    DEPARTMENT_NAMES,
    department_from_club_code,
    extract_dept_from_postal_code,
    haversine_distance_km,
    is_coordinate_in_department,
)

logger = logging.getLogger(__name__)

BAN_API_URL = "https://api-adresse.data.gouv.fr/search/"
NOMINATIM_API_URL = "https://nominatim.openstreetmap.org/search"
DEFAULT_USER_AGENT = "PyVolley/1.0 (https://github.com/VinCheetah/PyVolley)"


@dataclass
class GeocodingResult:
    """Résultat géocodé avec niveau de précision et rattachement territorial."""
    latitude: float
    longitude: float
    label: str
    score: float
    match_type: str  # "housenumber", "street", "locality", "municipality", "fallback"
    city: Optional[str] = None
    postcode: Optional[str] = None
    departement: Optional[str] = None
    context: Optional[str] = None
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

    def _make_key(self, query: str, postcode: Optional[str], departement: Optional[str] = None) -> str:
        norm_q = re.sub(r"\s+", " ", query.lower().strip())
        pc = (postcode or "").strip()
        dep = (departement or "").strip().upper()
        if dep:
            return f"{norm_q}##{pc}##{dep}"
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

    def is_not_found(self, query: str, postcode: Optional[str], departement: Optional[str] = None) -> bool:
        """Retourne True si l'adresse est déjà connue comme introuvable dans le cache."""
        key = self._make_key(query, postcode, departement)
        data = self._memory_cache.get(key)
        if data and data.get("_not_found"):
            return True
        if departement:
            legacy_key = self._make_key(query, postcode, None)
            legacy_data = self._memory_cache.get(legacy_key)
            if legacy_data and legacy_data.get("_not_found"):
                return True
        return False

    def get(self, query: str, postcode: Optional[str], departement: Optional[str] = None) -> Optional[GeocodingResult]:
        key = self._make_key(query, postcode, departement)
        data = self._memory_cache.get(key)
        if (not data or data.get("_not_found")) and departement:
            legacy_key = self._make_key(query, postcode, None)
            data = self._memory_cache.get(legacy_key)

        if data and not data.get("_not_found"):
            try:
                fields = {
                    k: v
                    for k, v in data.items()
                    if k in {
                        "latitude", "longitude", "label", "score", "match_type",
                        "city", "postcode", "departement", "context", "provider"
                    }
                }
                res = GeocodingResult(**fields)
                # Validation territoriale du cache : rejeter si hors-département
                if departement and res.latitude is not None and res.longitude is not None:
                    is_valid, dist = is_coordinate_in_department(res.latitude, res.longitude, departement)
                    if not is_valid:
                        logger.debug(
                            "Cache ignoré pour %s: résultat à %.1f km hors du dépt %s",
                            query, dist, departement
                        )
                        return None
                return res
            except Exception:
                return None
        return None

    def set(
        self,
        query: str,
        postcode: Optional[str],
        result: Optional[GeocodingResult],
        departement: Optional[str] = None,
    ) -> None:
        key = self._make_key(query, postcode, departement)
        if result is None:
            self._memory_cache[key] = {"_not_found": True, "ts": time.time()}
        else:
            self._memory_cache[key] = asdict(result)

    def set_not_found(self, query: str, postcode: Optional[str], departement: Optional[str] = None) -> None:
        """Enregistre un résultat négatif persistant (adresse introuvable)."""
        self.set(query, postcode, None, departement=departement)


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
    departement: Optional[str] = None,
    ligue: Optional[str] = None,
    timeout: float = 6.0,
) -> Optional[GeocodingResult]:
    """Interroge l'API Adresse officielle du gouvernement français avec contraintes territoriales."""
    if not query or not query.strip():
        return None

    params: dict[str, str | int | float] = {
        "q": query.strip(),
        "limit": 1,
    }
    if postcode and len(postcode) == 5 and postcode.isdigit():
        params["postcode"] = postcode
    if city:
        params["city"] = city
    if result_type:
        params["type"] = result_type

    # Biais géographique par coordonnées du centroïde départemental
    if departement:
        dep_code = departement.strip().upper()
        if len(dep_code) == 1 and dep_code.isdigit():
            dep_code = dep_code.zfill(2)
        centroid = DEPARTMENT_CENTROIDS.get(dep_code)
        if centroid:
            params["lat"] = round(centroid[0], 4)
            params["lon"] = round(centroid[1], 4)

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
            context = props.get("context")

            res_dept = None
            if context:
                m = re.match(r"^([0-9AB]{2,3})\s*,", context)
                if m:
                    res_dept = m.group(1)
            if not res_dept and res_postcode:
                res_dept = extract_dept_from_postal_code(res_postcode)

            # Validation territoriale stricte si département fourni
            if departement:
                is_in_dept, dist_km = is_coordinate_in_department(lat, lng, departement, max_distance_km=120.0)
                if not is_in_dept:
                    logger.debug(
                        "Rejet BAN (%s): hors-département attendu %s (distance=%.1f km, dépt BAN=%s)",
                        label, departement, dist_km, res_dept
                    )
                    return None

            return GeocodingResult(
                latitude=lat,
                longitude=lng,
                label=label,
                score=score,
                match_type=m_type,
                city=res_city,
                postcode=res_postcode,
                departement=res_dept or departement,
                context=context,
                provider="ban",
            )
    except Exception as e:
        logger.debug(f"Erreur appel BAN ({query}, {postcode}): {e}")
        return None


def _call_ban_csv_batch(
    rows: list[dict[str, str]],
    timeout: float = 15.0,
) -> dict[str, GeocodingResult]:
    """Interroge l'API CSV Batch de la Base Adresse Nationale pour géocoder un lot d'adresses.

    Args:
        rows: Liste de dicts avec 'id', 'q', 'postcode', 'city', et optionnellement 'departement', 'ligue'.

    Returns:
        Dictionnaire {id: GeocodingResult} pour les adresses localisées et validées.
    """
    if not rows:
        return {}

    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=["id", "q", "postcode", "city"])
    writer.writeheader()
    dept_by_id: dict[str, str] = {}

    for r in rows:
        item_id = str(r.get("id", ""))
        q_val = str(r.get("q", ""))
        pc_val = str(r.get("postcode", "") or "")
        city_val = str(r.get("city", "") or "")
        dept = str(r.get("departement", "") or "").strip().upper()
        ligue = str(r.get("ligue", "") or "").strip()

        if dept:
            if len(dept) == 1 and dept.isdigit():
                dept = dept.zfill(2)
            dept_by_id[item_id] = dept
            pc_dept = extract_dept_from_postal_code(pc_val) if pc_val else None
            # Si code postal absent ou en conflit manifeste avec le département du club
            if not pc_val or (pc_dept and pc_dept != dept):
                pc_val = ""
                dept_name = DEPARTMENT_NAMES.get(dept, "")
                if dept_name and dept_name.lower() not in q_val.lower():
                    q_val = f"{q_val} {dept_name}".strip()
                elif dept not in q_val:
                    q_val = f"{q_val} {dept}".strip()
            if ligue and ligue.lower() not in q_val.lower() and not pc_val:
                q_val = f"{q_val} {ligue}".strip()

        writer.writerow({
            "id": item_id,
            "q": q_val,
            "postcode": pc_val,
            "city": city_val,
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

            exp_dept = dept_by_id.get(item_id)
            if exp_dept:
                is_valid, dist_km = is_coordinate_in_department(lat, lon, exp_dept, max_distance_km=120.0)
                if not is_valid:
                    logger.debug(
                        "Rejet BAN batch CSV pour %s: résultat à %.1f km hors du dépt %s",
                        item_id, dist_km, exp_dept
                    )
                    continue

            res_pc = row.get("result_postcode") or row.get("postcode")
            res_dept = extract_dept_from_postal_code(res_pc) if res_pc else None
            results[item_id] = GeocodingResult(
                latitude=lat,
                longitude=lon,
                label=row.get("result_label") or row.get("q") or "",
                score=score,
                match_type=row.get("result_type") or "street",
                city=row.get("result_city") or row.get("city"),
                postcode=res_pc,
                departement=res_dept or exp_dept,
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
    departement: Optional[str] = None,
    ligue: Optional[str] = None,
    use_cache: bool = True,
    allow_nominatim: bool = False,
) -> Optional[GeocodingResult]:
    """Résout les coordonnées GPS précises d'une adresse avec stratégie de repli et contraintes territoriales.

    Ordre de priorité de la cascade :
    1. Cache local (validé pour le département attendu)
    2. BAN avec adresse nettoyée + code postal (si cohérent avec le département) + biais lat/lon du dépt
    3. BAN avec adresse nettoyée + commune + nom du département (ex: "Ille-et-Vilaine", "Côte-d'Or")
    4. BAN avec adresse nettoyée + commune + nom de la ligue
    5. BAN avec adresse brute + commune + département
    6. BAN avec nom de l'équipement sportif + commune + département
    7. Repli Nominatim OpenStreetMap (si allow_nominatim=True)
    8. BAN centroïde de la commune (+ département)
    9. Repli local sur coordonnées répertoriées (CITY_COORDINATES ou centroïde départemental)
    """
    postcode, city_name = extract_postal_and_city(ville)
    clean_addr = clean_street_address(adresse)

    # Normalisation du département attendu
    dept_code = departement.strip().upper() if departement else None
    if dept_code and len(dept_code) == 1 and dept_code.isdigit():
        dept_code = dept_code.zfill(2)

    # Détection et correction des codes postaux contradictoires
    if postcode and dept_code:
        pc_dept = extract_dept_from_postal_code(postcode)
        if pc_dept and pc_dept != dept_code:
            logger.debug(
                "Code postal erroné détecté (%s) pour département attendu %s (commune: %s) - écarté",
                postcode, dept_code, city_name
            )
            postcode = None  # Rejeter le mauvais code postal (ex: 33113 au lieu de 35630)

    if not dept_code and postcode:
        dept_code = extract_dept_from_postal_code(postcode)

    dept_name = DEPARTMENT_NAMES.get(dept_code) if dept_code else None

    cache = get_geocoding_cache() if use_cache else None

    # 1. Vérification dans le cache
    cache_key_addr = clean_addr or adresse or (nom or "")
    cache_q = f"{cache_key_addr} {city_name or ''}".strip()
    if cache:
        if cache.is_not_found(cache_q, postcode, dept_code):
            return None
        cached = cache.get(cache_q, postcode, dept_code)
        if cached:
            return cached

    result: Optional[GeocodingResult] = None

    # 2. BAN avec adresse nettoyée + code postal cohérent + biais départemental
    if clean_addr:
        q = f"{clean_addr} {city_name or ''}".strip()
        result = _call_ban_api(
            query=q,
            postcode=postcode,
            departement=dept_code,
            ligue=ligue,
        )
        if result and result.score >= 0.5:
            if cache:
                cache.set(cache_q, postcode, result, departement=dept_code)
            return result

    # 3. BAN avec adresse nettoyée + commune + nom du département (rattrape CP erronés ou absents)
    if clean_addr and city_name:
        dep_label = dept_name or dept_code or ""
        q = f"{clean_addr} {city_name} {dep_label}".strip()
        result = _call_ban_api(
            query=q,
            postcode=None,
            departement=dept_code,
            ligue=ligue,
        )
        if result and result.score >= 0.5:
            if cache:
                cache.set(cache_q, postcode, result, departement=dept_code)
            return result

    # 4. BAN avec adresse nettoyée + commune + ligue
    if clean_addr and city_name and ligue:
        q = f"{clean_addr} {city_name} {ligue}".strip()
        result = _call_ban_api(
            query=q,
            postcode=None,
            departement=dept_code,
            ligue=ligue,
        )
        if result and result.score >= 0.48:
            if cache:
                cache.set(cache_q, postcode, result, departement=dept_code)
            return result

    # 5. BAN avec adresse brute
    if adresse and adresse != clean_addr:
        dep_label = dept_name or dept_code or ""
        q = f"{adresse} {city_name or ''} {dep_label}".strip()
        result = _call_ban_api(
            query=q,
            postcode=postcode,
            departement=dept_code,
            ligue=ligue,
        )
        if result and result.score >= 0.48:
            if cache:
                cache.set(cache_q, postcode, result, departement=dept_code)
            return result

    # 6. BAN avec nom de la salle / équipement + commune + département
    if nom and city_name:
        clean_nom = re.sub(r"^(?:GM\d+\s*-\s*|SALLE\s*\d*\s*-\s*)", "", nom.strip(), flags=re.IGNORECASE)
        dep_label = dept_name or dept_code or ""
        q = f"{clean_nom} {city_name} {dep_label}".strip()
        result = _call_ban_api(
            query=q,
            postcode=postcode,
            departement=dept_code,
            ligue=ligue,
        )
        if result and result.score >= 0.45:
            if cache:
                cache.set(cache_q, postcode, result, departement=dept_code)
            return result

    # 7. Repli Nominatim (si autorisé)
    if allow_nominatim and (clean_addr or nom):
        target = clean_addr or nom
        dep_label = dept_name or dept_code or ""
        q = f"{target}, {city_name or ''} {dep_label}, France".strip(" ,")
        result = _call_nominatim_api(query=q)
        if result:
            if dept_code:
                is_valid, _ = is_coordinate_in_department(result.latitude, result.longitude, dept_code)
                if not is_valid:
                    result = None
            if result:
                if cache:
                    cache.set(cache_q, postcode, result, departement=dept_code)
                return result

    # 8. Centroïde de la commune via BAN (avec département)
    if city_name:
        dep_label = dept_name or dept_code or ""
        q = f"{city_name} {dep_label}".strip()
        result = _call_ban_api(
            query=q,
            postcode=postcode,
            result_type="municipality",
            departement=dept_code,
            ligue=ligue,
        )
        if result:
            result.match_type = "municipality"
            if cache:
                cache.set(cache_q, postcode, result, departement=dept_code)
            return result

    # 9. Repli local sur coordonnées de commune connues ou centroïde départemental (uniquement si aucune adresse de voirie)
    if not clean_addr and city_name:
        cleaned_c = city_name.upper().strip()
        if cleaned_c in CITY_COORDINATES:
            coords = CITY_COORDINATES[cleaned_c]
            if not dept_code or is_coordinate_in_department(coords[0], coords[1], dept_code)[0]:
                res = GeocodingResult(
                    latitude=coords[0],
                    longitude=coords[1],
                    label=f"{city_name} (Commune répertoriée)",
                    score=0.7,
                    match_type="municipality",
                    city=city_name,
                    departement=dept_code,
                    provider="city_coordinates",
                )
                if cache:
                    cache.set(cache_q, postcode, res, departement=dept_code)
                return res

    # Dernier recours sécurisé : centroïde du département attendu (uniquement si aucune adresse de voirie)
    if not clean_addr and dept_code and dept_code in DEPARTMENT_CENTROIDS:
        c_lat, c_lon = DEPARTMENT_CENTROIDS[dept_code]
        res = GeocodingResult(
            latitude=c_lat,
            longitude=c_lon,
            label=f"{dept_name or dept_code} (Centroïde départemental)",
            score=0.4,
            match_type="dept_centroid",
            city=city_name,
            departement=dept_code,
            provider="dept_centroid",
        )
        if cache:
            cache.set(cache_q, postcode, res, departement=dept_code)
        return res

    # Enregistrement de l'échec dans le cache
    if cache:
        cache.set_not_found(cache_q, postcode, departement=dept_code)

    return None


def geocode_addresses_batch(
    items: list[dict],
    use_cache: bool = True,
    allow_nominatim: bool = False,
) -> dict[str, Optional[GeocodingResult]]:
    """Géocode un lot d'adresses de façon optimisée (cache -> BAN CSV batch -> repli unitaire avec département/ligue).

    Args:
        items: Liste de dicts avec clés :
               - 'id': identifiant unique (ex: "club_0622126_salle_1")
               - 'adresse': adresse voirie optionnelle
               - 'ville': commune ou code postal + commune
               - 'nom': nom optionnel (équipement, club)
               - 'departement': code département optionnel (ex: "38", "21")
               - 'ligue': nom de ligue optionnel
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
                "departement": raw_item.get("departement"),
                "ligue": raw_item.get("ligue"),
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
                "departement": None,
                "ligue": None,
            })

    for item in normalized_items:
        item_id = item["id"]
        adresse = item.get("adresse")
        ville = item.get("ville")
        nom = item.get("nom")
        dept = item.get("departement")
        ligue = item.get("ligue")

        postcode, city_name = extract_postal_and_city(ville)
        clean_addr = clean_street_address(adresse)
        cache_key_addr = clean_addr or adresse or (nom or "")
        cache_q = f"{cache_key_addr} {city_name or ''}".strip()

        # 1. Vérification dans le cache (positif ou échec déjà connu)
        if cache:
            if cache.is_not_found(cache_q, postcode, dept):
                results[item_id] = None
                continue
            cached = cache.get(cache_q, postcode, dept)
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
                "departement": dept or "",
                "ligue": ligue or "",
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
                cache.set(cache_q, postcode, res, departement=it.get("departement"))

    # 3. Repli unitaire pour les éléments non résolus par le batch
    for item in normalized_items:
        item_id = item["id"]
        if item_id not in results or results[item_id] is None:
            postcode, city_name = extract_postal_and_city(item.get("ville"))
            clean_addr = clean_street_address(item.get("adresse"))
            cache_key_addr = clean_addr or item.get("adresse") or (item.get("nom") or "")
            cache_q = f"{cache_key_addr} {city_name or ''}".strip()
            dept = item.get("departement")
            if cache and cache.is_not_found(cache_q, postcode, dept):
                results[item_id] = None
                continue

            res = geocode_address(
                adresse=item.get("adresse"),
                ville=item.get("ville"),
                nom=item.get("nom"),
                departement=dept,
                ligue=item.get("ligue"),
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
    """Géocode une instance de SalleClubDB et met à jour ses coordonnées en contraignant sur son club."""
    club = getattr(salle, "club", None)
    club_dept = getattr(club, "departement", None)
    if not club_dept and getattr(club, "code_ffvb", None):
        club_dept = department_from_club_code(club.code_ffvb)
    club_ligue = getattr(club, "ligue", None)

    if not force and salle.latitude is not None and salle.longitude is not None:
        if club_dept:
            is_valid, _ = is_coordinate_in_department(salle.latitude, salle.longitude, club_dept)
            if is_valid:
                return GeocodingResult(
                    latitude=salle.latitude,
                    longitude=salle.longitude,
                    label=salle.adresse or salle.nom or "Existant",
                    score=1.0,
                    match_type="existing",
                    city=salle.ville,
                    departement=club_dept,
                )
            else:
                logger.info("Coordonnées de salle #%s hors du dépt %s -> re-géocodage forcé", salle.id, club_dept)
        else:
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
        ville=salle.ville or (club.ville if club else None),
        nom=salle.nom,
        departement=club_dept,
        ligue=club_ligue,
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
    """Positionne un ClubDB sur les coordonnées de sa salle principale (main venue) ou de son siège, contraint par département."""
    club_dept = getattr(club, "departement", None)
    if not club_dept and getattr(club, "code_ffvb", None):
        club_dept = department_from_club_code(club.code_ffvb)
    club_ligue = getattr(club, "ligue", None)

    if not force and club.latitude is not None and club.longitude is not None:
        if club_dept:
            is_valid, _ = is_coordinate_in_department(club.latitude, club.longitude, club_dept)
            if is_valid:
                return GeocodingResult(
                    latitude=club.latitude,
                    longitude=club.longitude,
                    label=club.nom or "Existant",
                    score=1.0,
                    match_type="existing",
                    city=club.ville,
                    departement=club_dept,
                )
            else:
                logger.info("Coordonnées de club %s hors du dépt %s -> re-géocodage forcé", club.code_ffvb, club_dept)
        else:
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
                departement=club_dept,
                provider="venue",
            )

    # 2. Géocodage sur l'adresse du siège social si disponible
    if not res:
        addr_siege = getattr(club, "adresse_siege", None)
        cp_siege = getattr(club, "code_postal_siege", None)
        ville_s = getattr(club, "ville_siege", None)
        city_input = f"{cp_siege or ''} {ville_s or ''}".strip() or getattr(club, "ville", None)

        if addr_siege or city_input:
            res = geocode_address(
                adresse=addr_siege,
                ville=city_input,
                nom=club.nom,
                departement=club_dept,
                ligue=club_ligue,
            )

    # 3. Fallback sur la commune du club
    if not res and getattr(club, "ville", None):
        res = geocode_address(
            adresse=None,
            ville=club.ville,
            nom=club.nom,
            departement=club_dept,
            ligue=club_ligue,
        )

    # 4. Repli sécurisé sur le centroïde du département
    if not res and club_dept and club_dept in DEPARTMENT_CENTROIDS:
        c_lat, c_lon = DEPARTMENT_CENTROIDS[club_dept]
        res = GeocodingResult(
            latitude=c_lat,
            longitude=c_lon,
            label=f"{club.nom} (Centroïde dépt {club_dept})",
            score=0.4,
            match_type="dept_centroid",
            city=club.ville,
            departement=club_dept,
            provider="dept_centroid",
        )

    if res:
        club.latitude = res.latitude
        club.longitude = res.longitude
        if session and commit:
            session.commit()
    return res


# ── Audit & Diagnostic de Cohérence Territoriale ───────────────────

def audit_geocoding_consistency(session, max_distance_km: float = 120.0) -> dict:
    """Audite l'ensemble des clubs et salles en base pour identifier les anomalies de positionnement.

    Une anomalie correspond à une coordonnée GPS située à plus de `max_distance_km`
    (défaut 120 km) du centroïde du département officiel rattaché à l'entité.
    """
    from pyvolley.database.models import ClubDB, SalleClubDB

    salles = session.query(SalleClubDB).all()
    clubs = session.query(ClubDB).all()

    salles_geocoded = 0
    salle_outliers = []
    for sa in salles:
        if sa.latitude is None or sa.longitude is None:
            continue
        salles_geocoded += 1
        c = sa.club
        c_dept = getattr(c, "departement", None) if c else None
        if not c_dept and c and getattr(c, "code_ffvb", None):
            c_dept = department_from_club_code(c.code_ffvb)

        if c_dept:
            is_valid, dist = is_coordinate_in_department(
                sa.latitude, sa.longitude, c_dept, max_distance_km=max_distance_km
            )
            if not is_valid:
                salle_outliers.append({
                    "id": sa.id,
                    "nom": sa.nom or f"Salle {sa.numero}",
                    "adresse": sa.adresse,
                    "ville": sa.ville,
                    "club_id": sa.club_id,
                    "club_nom": c.nom if c else None,
                    "club_code": c.code_ffvb if c else None,
                    "expected_dept": c_dept,
                    "latitude": sa.latitude,
                    "longitude": sa.longitude,
                    "distance_km": round(dist, 1),
                })

    clubs_geocoded = 0
    club_outliers = []
    for c in clubs:
        if c.latitude is None or c.longitude is None:
            continue
        clubs_geocoded += 1
        c_dept = getattr(c, "departement", None)
        if not c_dept and getattr(c, "code_ffvb", None):
            c_dept = department_from_club_code(c.code_ffvb)
        if not c_dept and getattr(c, "code_postal_siege", None):
            c_dept = extract_dept_from_postal_code(c.code_postal_siege)

        if c_dept:
            is_valid, dist = is_coordinate_in_department(
                c.latitude, c.longitude, c_dept, max_distance_km=max_distance_km
            )
            if not is_valid:
                club_outliers.append({
                    "id": c.id,
                    "nom": c.nom,
                    "code_ffvb": c.code_ffvb,
                    "adresse_siege": c.adresse_siege,
                    "ville_siege": c.ville_siege,
                    "ville": c.ville,
                    "expected_dept": c_dept,
                    "latitude": c.latitude,
                    "longitude": c.longitude,
                    "distance_km": round(dist, 1),
                })

    salle_outliers.sort(key=lambda x: x["distance_km"], reverse=True)
    club_outliers.sort(key=lambda x: x["distance_km"], reverse=True)

    return {
        "salles_total": len(salles),
        "salles_geocoded": salles_geocoded,
        "salle_outliers": salle_outliers,
        "clubs_total": len(clubs),
        "clubs_geocoded": clubs_geocoded,
        "club_outliers": club_outliers,
    }


def fix_geocoded_outliers(
    session,
    max_distance_km: float = 120.0,
    on_progress: Optional[Callable[[int, int, str], None]] = None,
) -> dict:
    """Re-géocode spécifiquement les entités hors-département avec les contraintes territoriales renforcées."""
    from pyvolley.database.models import ClubDB, SalleClubDB

    audit = audit_geocoding_consistency(session, max_distance_km=max_distance_km)
    s_outliers = audit["salle_outliers"]
    c_outliers = audit["club_outliers"]

    total_to_fix = len(s_outliers) + len(c_outliers)
    fixed_salles = 0
    fixed_clubs = 0
    current = 0

    # 1. Corriger les salles
    for o in s_outliers:
        current += 1
        if on_progress:
            on_progress(current, total_to_fix, f"Salle: {o['nom']}")
        sa = session.get(SalleClubDB, o["id"])
        if sa:
            res = geocode_salle_entity(sa, session=session, force=True)
            if res:
                c_dept = o["expected_dept"]
                is_now_valid, _ = is_coordinate_in_department(
                    sa.latitude, sa.longitude, c_dept, max_distance_km=max_distance_km
                )
                if is_now_valid:
                    fixed_salles += 1
            time.sleep(0.03)

    # 2. Corriger les clubs
    for o in c_outliers:
        current += 1
        if on_progress:
            on_progress(current, total_to_fix, f"Club: {o['nom']}")
        c = session.get(ClubDB, o["id"])
        if c:
            res = geocode_club_entity(c, session=session, force=True)
            if res:
                c_dept = o["expected_dept"]
                is_now_valid, _ = is_coordinate_in_department(
                    c.latitude, c.longitude, c_dept, max_distance_km=max_distance_km
                )
                if is_now_valid:
                    fixed_clubs += 1
            time.sleep(0.03)

    session.commit()
    cache = get_geocoding_cache()
    cache.save()

    post_audit = audit_geocoding_consistency(session, max_distance_km=max_distance_km)

    return {
        "initial_salle_outliers": len(s_outliers),
        "fixed_salles": fixed_salles,
        "remaining_salle_outliers": len(post_audit["salle_outliers"]),
        "initial_club_outliers": len(c_outliers),
        "fixed_clubs": fixed_clubs,
        "remaining_club_outliers": len(post_audit["club_outliers"]),
    }



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
