"""
Routes API — Carte interactive (locations géographiques).
"""

from typing import Optional, List

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session, joinedload

from pyvolley.api.dependencies import get_session
from pyvolley.database.models import ClubDB, SalleClubDB, MatchDB, CompetitionDB, EquipeDB

router = APIRouter(prefix="/map", tags=["map"])


# ── Schemas ─────────────────────────────────────────────────────

class MapMarker(BaseModel):
    """Single marker for the interactive map."""
    lat: float
    lng: float
    label: str
    entity_type: str  # "club", "salle", "match", "competition"
    entity_id: int
    popup_html: str
    icon_color: str = "blue"


class MapResponse(BaseModel):
    """Response containing all markers for the map."""
    markers: List[MapMarker] = []
    center_lat: float = 46.6
    center_lng: float = 2.3
    zoom: int = 6


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
        None, description="Filter by entity type: club, salle, match, competition"
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
        query = session.query(ClubDB).filter(
            ClubDB.latitude.isnot(None), ClubDB.longitude.isnot(None),
        )
        if club_id is not None:
            query = query.filter(ClubDB.id == club_id)
        if departement:
            query = query.filter(ClubDB.departement == departement)
        for club in query.limit(limit).all():
            markers.append(MapMarker(
                lat=club.latitude, lng=club.longitude,
                label=club.nom, entity_type="club", entity_id=club.id,
                popup_html=_club_popup(club), icon_color="blue",
            ))

    # ── Venue (salle) markers ───────────────────────────────────
    if entity_type in (None, "salle"):
        query = session.query(SalleClubDB).options(
            joinedload(SalleClubDB.club),
        ).filter(
            SalleClubDB.latitude.isnot(None), SalleClubDB.longitude.isnot(None),
        )
        if club_id is not None:
            query = query.filter(SalleClubDB.club_id == club_id)
        if departement:
            query = query.join(ClubDB).filter(ClubDB.departement == departement)
        for salle in query.limit(limit).all():
            markers.append(MapMarker(
                lat=salle.latitude, lng=salle.longitude,
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
                joinedload(MatchDB.equipe_b),
            )
            .filter(
                (SalleClubDB.latitude.isnot(None))
                | (ClubDB.latitude.isnot(None)),
            )
        )
        if competition_id is not None:
            query = query.filter(MatchDB.competition_id == competition_id)
        if equipe_id is not None:
            query = query.filter(
                (MatchDB.equipe_a_id == equipe_id)
                | (MatchDB.equipe_b_id == equipe_id)
            )
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
                    if salle.latitude and salle.longitude:
                        lat, lng = salle.latitude, salle.longitude
                        break
                if lat is None and club.latitude and club.longitude:
                    lat, lng = club.latitude, club.longitude

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
