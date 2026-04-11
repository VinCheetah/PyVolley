"""
Routes API — Carte interactive (locations géographiques).
"""

from typing import Optional, List
from math import sin, cos, radians

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session, joinedload

from pyvolley.api.dependencies import get_session
from pyvolley.database.models import ClubDB, SalleClubDB, MatchDB, EquipeDB, ParticipationMatchDB
from pyvolley.core.geo_data import get_department_for_city

router = APIRouter(prefix="/map", tags=["map"])


# ── Schemas ─────────────────────────────────────────────────────

class MapMarker(BaseModel):
    """Single marker for the interactive map."""
    lat: float
    lng: float
    label: str
    entity_type: str  # "club", "salle", "match"
    entity_id: int
    popup_html: str
    icon_color: str = "blue"


class MapResponse(BaseModel):
    """Response containing all markers for the map."""
    markers: List[MapMarker] = Field(default_factory=list)
    center_lat: float = 46.6
    center_lng: float = 2.3
    zoom: int = 6


# ── Fallback geolocation (department centroids) ───────────────

_DEPARTMENT_CENTROIDS: dict[str, tuple[float, float]] = {
    "01": (46.20, 5.23),  # Ain
    "03": (46.35, 3.36),  # Allier
    "07": (44.75, 4.60),  # Ardèche
    "26": (44.93, 5.05),  # Drôme
    "38": (45.19, 5.72),  # Isère
    "42": (45.53, 4.39),  # Loire
    "43": (45.05, 3.88),  # Haute-Loire
    "63": (45.77, 3.08),  # Puy-de-Dôme
    "69": (45.76, 4.84),  # Rhône
    "73": (45.56, 6.17),  # Savoie
    "74": (46.00, 6.40),  # Haute-Savoie
}


def _normalize_departement(code: Optional[str]) -> Optional[str]:
    if not code:
        return None
    clean = code.strip().upper()
    if not clean:
        return None
    if clean.isdigit() and len(clean) == 1:
        return clean.zfill(2)
    return clean


def _resolve_marker_coords(
    *,
    latitude: Optional[float],
    longitude: Optional[float],
    ville: Optional[str],
    departement: Optional[str],
    entity_id: int,
) -> tuple[float, float] | None:
    """Resolve marker coordinates.

    Priority:
    1) Exact lat/lng from DB
    2) Department centroid from explicit departement
    3) Department centroid inferred from ville
    """
    if latitude is not None and longitude is not None:
        return latitude, longitude

    dept = _normalize_departement(departement)
    if not dept and ville:
        dept = _normalize_departement(get_department_for_city(ville))
    if not dept:
        return None

    centroid = _DEPARTMENT_CENTROIDS.get(dept)
    if centroid is None:
        return None

    # Deterministic jitter to avoid exact overlap on the same centroid.
    # Radius ~1.2km max: subtle visual separation while staying representative.
    angle = radians((entity_id * 37) % 360)
    radius = ((entity_id % 7) - 3) * 0.003
    lat = centroid[0] + sin(angle) * radius
    lng = centroid[1] + cos(angle) * radius
    return lat, lng


# ── Helpers ─────────────────────────────────────────────────────

def _club_popup(club: ClubDB) -> str:
    """Build popup HTML for a club marker."""
    parts = [f'<strong><a href="/clubs/{club.id}">{club.nom}</a></strong>']
    if club.ville:
        parts.append(f"<br><em>{club.ville}</em>")
    if club.departement:
        parts.append(f" ({club.departement})")
    return "".join(parts)


def _salle_popup(salle: SalleClubDB) -> str:
    """Build popup HTML for a venue marker."""
    name = salle.nom or f"Salle {salle.numero}"
    parts = [f'<strong>{name}</strong>']
    if salle.club:
        parts.append(f'<br><a href="/clubs/{salle.club_id}">{salle.club.nom}</a>')
    if salle.adresse:
        parts.append(f"<br>{salle.adresse}")
    if salle.ville:
        parts.append(f", {salle.ville}" if salle.adresse else f"<br>{salle.ville}")
    if salle.capacite:
        parts.append(f"<br>Capacité : {salle.capacite}")
    return "".join(parts)


def _match_popup(match: MatchDB) -> str:
    """Build popup HTML for a match marker."""
    ea = match.equipe_a.nom if match.equipe_a else "?"
    eb = match.equipe_b.nom if match.equipe_b else "?"
    parts = [f'<strong><a href="/matchs/{match.id}">{ea} vs {eb}</a></strong>']
    if match.score_sets:
        parts.append(f"<br>Score : {match.score_sets}")
    if match.salle:
        parts.append(f"<br>{match.salle}")
    if match.date_match:
        parts.append(f"<br>{match.date_match.strftime('%d/%m/%Y')}")
    return "".join(parts)


# ── Endpoints ───────────────────────────────────────────────────

@router.get("/locations", response_model=MapResponse)
async def get_map_locations(
    entity_type: Optional[str] = Query(
        None, description="Filter by entity type: club, salle, match"
    ),
    club_id: Optional[int] = Query(None, description="Filter by club ID"),
    competition_id: Optional[int] = Query(None, description="Filter by competition ID"),
    equipe_id: Optional[int] = Query(None, description="Filter by team ID"),
    joueur_id: Optional[int] = Query(None, description="Filter by player ID"),
    saison_id: Optional[int] = Query(None, description="Filter by season ID"),
    departement: Optional[str] = Query(None, description="Filter by department code"),
    limit: int = Query(500, ge=1, le=2000),
    session: Session = Depends(get_session),
) -> MapResponse:
    """Return geo-located markers for the interactive map.

    Supports filtering by entity type, club, competition, team, player,
    season and department.  Only entities with valid coordinates are returned.
    """
    markers: list[MapMarker] = []

    # ── Club markers ────────────────────────────────────────────
    if entity_type in (None, "club"):
        query = session.query(ClubDB)
        if club_id is not None:
            query = query.filter(ClubDB.id == club_id)
        if departement:
            query = query.filter(ClubDB.departement == departement)
        for club in query.limit(limit).all():
            coords = _resolve_marker_coords(
                latitude=club.latitude,
                longitude=club.longitude,
                ville=club.ville,
                departement=club.departement,
                entity_id=club.id,
            )
            if coords is None:
                continue
            markers.append(MapMarker(
                lat=coords[0], lng=coords[1],
                label=club.nom, entity_type="club", entity_id=club.id,
                popup_html=_club_popup(club), icon_color="blue",
            ))

    # ── Venue (salle) markers ───────────────────────────────────
    if entity_type in (None, "salle"):
        query = session.query(SalleClubDB).options(
            joinedload(SalleClubDB.club),
        )
        if club_id is not None:
            query = query.filter(SalleClubDB.club_id == club_id)
        if departement:
            query = query.join(ClubDB).filter(ClubDB.departement == departement)
        for salle in query.limit(limit).all():
            coords = _resolve_marker_coords(
                latitude=salle.latitude,
                longitude=salle.longitude,
                ville=salle.ville or (salle.club.ville if salle.club else None),
                departement=salle.club.departement if salle.club else None,
                entity_id=salle.id,
            )
            if coords is None:
                continue
            markers.append(MapMarker(
                lat=coords[0], lng=coords[1],
                label=salle.nom or f"Salle {salle.numero}",
                entity_type="salle", entity_id=salle.id,
                popup_html=_salle_popup(salle), icon_color="cyan",
            ))

    # ── Match markers (via club_a venue) ────────────────────────
    if entity_type in (None, "match"):
        # Matches don't have coords directly — use the home club's venue
        query = (
            session.query(MatchDB)
            .join(EquipeDB, MatchDB.equipe_a_id == EquipeDB.id)
            .join(ClubDB, EquipeDB.club_id == ClubDB.id)
            .outerjoin(SalleClubDB, SalleClubDB.club_id == ClubDB.id)
            .options(
                joinedload(MatchDB.equipe_a),
                joinedload(MatchDB.equipe_a).joinedload(EquipeDB.club).joinedload(ClubDB.salles),
                joinedload(MatchDB.equipe_b),
            )
        )
        if competition_id is not None:
            query = query.filter(MatchDB.competition_id == competition_id)
        if equipe_id is not None:
            query = query.filter(
                (MatchDB.equipe_a_id == equipe_id)
                | (MatchDB.equipe_b_id == equipe_id)
            )
        if joueur_id is not None:
            query = query.join(
                ParticipationMatchDB,
                ParticipationMatchDB.match_id == MatchDB.id,
            ).filter(ParticipationMatchDB.joueur_id == joueur_id)
        if saison_id is not None:
            query = query.filter(MatchDB.saison_id == saison_id)
        if club_id is not None:
            query = query.filter(EquipeDB.club_id == club_id)

        seen_match_ids: set[int] = set()
        for match in query.limit(limit).all():
            if match.id in seen_match_ids:
                continue
            seen_match_ids.add(match.id)

            # Prefer venue coords, fall back to club coords
            lat = lng = None
            if match.equipe_a and match.equipe_a.club:
                club = match.equipe_a.club
                # Try first venue
                for salle in getattr(club, "salles", []):
                    coords = _resolve_marker_coords(
                        latitude=salle.latitude,
                        longitude=salle.longitude,
                        ville=salle.ville or club.ville,
                        departement=club.departement,
                        entity_id=salle.id,
                    )
                    if coords is not None:
                        lat, lng = coords
                        break
                if lat is None:
                    coords = _resolve_marker_coords(
                        latitude=club.latitude,
                        longitude=club.longitude,
                        ville=club.ville,
                        departement=club.departement,
                        entity_id=club.id,
                    )
                    if coords is not None:
                        lat, lng = coords

            if lat is not None and lng is not None:
                markers.append(MapMarker(
                    lat=lat, lng=lng,
                    label=f"{match.equipe_a.nom if match.equipe_a else '?'} vs "
                          f"{match.equipe_b.nom if match.equipe_b else '?'}",
                    entity_type="match", entity_id=match.id,
                    popup_html=_match_popup(match), icon_color="gold",
                ))

    # ── Compute center from markers ─────────────────────────────
    center_lat, center_lng, zoom = 46.6, 2.3, 6
    if markers:
        lats = [m.lat for m in markers]
        lngs = [m.lng for m in markers]
        center_lat = sum(lats) / len(lats)
        center_lng = sum(lngs) / len(lngs)
        # Adjust zoom based on spread
        lat_spread = max(lats) - min(lats)
        lng_spread = max(lngs) - min(lngs)
        spread = max(lat_spread, lng_spread)
        if spread < 0.05:
            zoom = 14
        elif spread < 0.2:
            zoom = 12
        elif spread < 1:
            zoom = 10
        elif spread < 3:
            zoom = 8
        else:
            zoom = 6

    return MapResponse(markers=markers, center_lat=center_lat, center_lng=center_lng, zoom=zoom)
