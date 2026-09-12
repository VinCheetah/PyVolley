"""
Routes API — Carte interactive (locations géographiques).

Fournit les points géolocalisés (clubs, salles, matchs) avec métadonnées enrichies
pour le composant de carte Leaflet.
"""

from typing import Optional, List
import urllib.parse

from fastapi import APIRouter, Depends, Query, Response
from pydantic import BaseModel, Field
from sqlalchemy import or_
from sqlalchemy.orm import Session, joinedload, selectinload

from pyvolley.api.dependencies import get_session
from pyvolley.database.models import (
    ClubDB,
    SalleClubDB,
    MatchDB,
    EquipeDB,
    ParticipationMatchDB,
    SetDB,
)
from pyvolley.core.geo_data import resolve_entity_coordinates

router = APIRouter(prefix="/map", tags=["map"])


# ── Schemas ─────────────────────────────────────────────────────

class MapMarker(BaseModel):
    """Marqueur enrichi pour la carte interactive."""
    lat: float
    lng: float
    label: str
    entity_type: str  # "club", "salle", "match"
    entity_id: int
    popup_html: str
    icon_color: str = "blue"
    icon_type: str = "club"  # "club", "salle", "match_win", "match_loss", "match_pending"
    sublabel: Optional[str] = None
    badge: Optional[str] = None
    url: Optional[str] = None
    departement: Optional[str] = None
    ville: Optional[str] = None
    postcode: Optional[str] = None


class MapResponse(BaseModel):
    """Réponse contenant l'ensemble des marqueurs et cadrage."""
    markers: List[MapMarker] = Field(default_factory=list)
    center_lat: float = 46.6
    center_lng: float = 2.3
    zoom: int = 6


# ── Helpers de mise en page des Popups ───────────────────────────

def _escape(text: Optional[str]) -> str:
    if not text:
        return ""
    return (
        str(text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _club_popup(club: ClubDB) -> str:
    """Génère la popup sportive d'un club."""
    nom = _escape(club.nom)
    ville = _escape(club.ville)
    dept = _escape(club.departement)
    salles_count = len(getattr(club, "salles", []) or [])
    equipes_count = len(getattr(club, "equipes", []) or [])

    logo_html = ""
    if club.logo_url:
        logo_html = (
            f'<img src="{_escape(club.logo_url)}" alt="{nom}" '
            f'class="w-10 h-10 object-contain rounded-lg flex-shrink-0 bg-slate-900/50 p-1" '
            f'onerror="this.style.display=\'none\'">'
        )
    else:
        initials = (club.nom[:2] if club.nom else "CL").upper()
        logo_html = (
            f'<div class="w-10 h-10 rounded-lg flex items-center justify-center font-bold text-xs '
            f'bg-gradient-to-br from-blue-600 to-cyan-600 text-white flex-shrink-0 shadow-sm">'
            f'{_escape(initials)}</div>'
        )

    location_str = ""
    if ville and dept:
        location_str = f"{ville} ({dept})"
    elif ville or dept:
        location_str = ville or dept

    stats_parts = []
    if equipes_count > 0:
        stats_parts.append(f"{equipes_count} équipe{'s' if equipes_count > 1 else ''}")
    if salles_count > 0:
        stats_parts.append(f"{salles_count} salle{'s' if salles_count > 1 else ''}")
    stats_str = " · ".join(stats_parts) if stats_parts else "Club FFVB"

    return f"""
    <div class="pyvolley-popup-card">
      <div class="pyvolley-popup-header">
        {logo_html}
        <div class="min-w-0 flex-1">
          <div class="pyvolley-popup-category">Club</div>
          <a href="/clubs/{club.id}" class="pyvolley-popup-title" title="{nom}">{nom}</a>
          <div class="pyvolley-popup-sub">{location_str}</div>
        </div>
      </div>
      <div class="pyvolley-popup-body">
        <div class="pyvolley-popup-meta">
          <span>{stats_str}</span>
        </div>
      </div>
      <div class="pyvolley-popup-actions">
        <a href="/clubs/{club.id}" class="pyvolley-btn-popup-primary">
          Voir la fiche du club
          <svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M5 12h14"/><path d="m12 5 7 7-7 7"/></svg>
        </a>
      </div>
    </div>
    """


def _salle_popup(salle: SalleClubDB) -> str:
    """Génère la popup détaillée d'une salle/gymnase."""
    nom = _escape(salle.nom or f"Salle {salle.numero}")
    club_nom = _escape(salle.club.nom if salle.club else "")
    club_id = salle.club_id
    adresse = _escape(salle.adresse or "")
    ville = _escape(salle.ville or "")

    full_addr = f"{salle.adresse or ''} {salle.ville or ''}".strip()
    encoded_dest = urllib.parse.quote_plus(full_addr or nom)
    directions_url = f"https://www.google.com/maps/dir/?api=1&destination={encoded_dest}"

    meta_items = []
    if salle.capacite:
        meta_items.append(f"Capacité : {salle.capacite} pl.")
    if salle.sol:
        meta_items.append(f"Sol : {_escape(salle.sol)}")

    meta_html = ""
    if meta_items:
        meta_html = f'<div class="pyvolley-popup-meta">{" · ".join(meta_items)}</div>'

    transport_html = ""
    if salle.transport:
        transport_html = f'<div class="pyvolley-popup-transport">🚌 {_escape(salle.transport)}</div>'

    club_link = ""
    if club_nom and club_id:
        club_link = f'<div class="pyvolley-popup-sub">Club : <a href="/clubs/{club_id}">{club_nom}</a></div>'

    return f"""
    <div class="pyvolley-popup-card">
      <div class="pyvolley-popup-header">
        <div class="w-10 h-10 rounded-lg flex items-center justify-center bg-gradient-to-br from-cyan-600 to-teal-600 text-white flex-shrink-0 shadow-sm">
          <svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M6 22V4a2 2 0 0 1 2-2h8a2 2 0 0 1 2 2v18Z"/><path d="M6 12H4a2 2 0 0 0-2 2v6a2 2 0 0 0 2 2h2"/><path d="M18 9h2a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2h-2"/><path d="M10 6h4"/><path d="M10 10h4"/><path d="M10 14h4"/><path d="M10 18h4"/></svg>
        </div>
        <div class="min-w-0 flex-1">
          <div class="pyvolley-popup-category">Gymnase / Salle</div>
          <div class="pyvolley-popup-title" title="{nom}">{nom}</div>
          {club_link}
        </div>
      </div>
      <div class="pyvolley-popup-body">
        {f'<div class="text-xs text-slate-300 mb-1">{adresse}{", " + ville if adresse and ville else ville}</div>' if (adresse or ville) else ''}
        {meta_html}
        {transport_html}
      </div>
      <div class="pyvolley-popup-actions">
        <a href="{directions_url}" target="_blank" rel="noopener noreferrer" class="pyvolley-btn-popup-secondary">
          <svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polygon points="3 11 22 2 13 21 11 13 3 11"/></svg>
          Itinéraire GPS
        </a>
      </div>
    </div>
    """


def _match_popup(match: MatchDB, perspective_team_id: Optional[int] = None) -> str:
    """Génère la popup sportive d'un match avec scores détaillés."""
    ea = _escape(match.equipe_a.nom if match.equipe_a else "Équipe A")
    eb = _escape(match.equipe_b.nom if match.equipe_b else "Équipe B")
    competition_nom = _escape(match.competition.nom if match.competition else "")
    date_str = match.date_match.strftime("%d/%m/%Y") if match.date_match else ""
    heure_str = f" à {match.heure_match}" if match.heure_match else ""
    salle_str = _escape(match.salle or "")

    # Déterminer le résultat (victoire/défaite ou statut)
    score_sets = match.score_sets or (
        f"{match.sets_equipe_a}/{match.sets_equipe_b}"
        if (match.sets_equipe_a or match.sets_equipe_b)
        else None
    )

    badge_status = ""
    winner_a = False
    winner_b = False

    if match.match_joue and score_sets:
        try:
            parts = score_sets.replace("-", "/").split("/")
            sa, sb = int(parts[0]), int(parts[1])
            winner_a = sa > sb
            winner_b = sb > sa
        except (ValueError, IndexError):
            pass

    if match.forfait:
        badge_status = '<span class="pyvolley-badge-pill pyvolley-badge-red">Forfait</span>'
    elif match.match_joue:
        badge_status = '<span class="pyvolley-badge-pill pyvolley-badge-green">Terminé</span>'
    else:
        badge_status = '<span class="pyvolley-badge-pill pyvolley-badge-blue">À venir</span>'

    # Détails des scores de sets (ex: 25-21, 23-25...)
    sets_pills = []
    if match.sets:
        for s in sorted(match.sets, key=lambda x: x.numero):
            if s.score_a is not None and s.score_b is not None:
                sets_pills.append(f"{s.score_a}-{s.score_b}")
    sets_breakdown = " · ".join(sets_pills) if sets_pills else ""

    return f"""
    <div class="pyvolley-popup-card">
      <div class="pyvolley-popup-header">
        <div class="w-10 h-10 rounded-lg flex items-center justify-center bg-gradient-to-br from-amber-500 to-orange-600 text-white flex-shrink-0 shadow-sm">
          🏐
        </div>
        <div class="min-w-0 flex-1">
          <div class="flex items-center justify-between gap-1 mb-0.5">
            <span class="pyvolley-popup-category">{competition_nom or "Match"}</span>
            {badge_status}
          </div>
          <div class="text-xs text-slate-400">{date_str}{heure_str}</div>
        </div>
      </div>

      <div class="pyvolley-popup-match-board">
        <div class="pyvolley-popup-team {'font-bold text-white' if winner_a else 'text-slate-300'}">
          <span class="truncate">{ea}</span>
          <span class="pyvolley-score-digit {'text-emerald-400' if winner_a else ''}">{match.sets_equipe_a}</span>
        </div>
        <div class="pyvolley-popup-team {'font-bold text-white' if winner_b else 'text-slate-300'}">
          <span class="truncate">{eb}</span>
          <span class="pyvolley-score-digit {'text-emerald-400' if winner_b else ''}">{match.sets_equipe_b}</span>
        </div>
      </div>

      {f'<div class="pyvolley-popup-sets-breakdown">{sets_breakdown}</div>' if sets_breakdown else ''}

      {f'<div class="pyvolley-popup-venue"><svg xmlns="http://www.w3.org/2000/svg" width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M20 10c0 6-8 12-8 12s-8-6-8-12a8 8 0 0 1 16 0Z"/><circle cx="12" cy="10" r="3"/></svg> {salle_str}</div>' if salle_str else ''}

      <div class="pyvolley-popup-actions">
        <a href="/matchs/{match.id}" class="pyvolley-btn-popup-primary">
          Feuille de match
          <svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M5 12h14"/><path d="m12 5 7 7-7 7"/></svg>
        </a>
      </div>
    </div>
    """


# ── Endpoints ───────────────────────────────────────────────────

@router.get("/locations", response_model=MapResponse)
async def get_map_locations(
    response: Response = None,
    entity_type: Optional[str] = Query(
        None, description="Filtrer par type d'entité : club, salle, match (ou liste ex: club,salle)"
    ),
    club_id: Optional[int] = Query(None, description="Filtrer par ID de club"),
    competition_id: Optional[int] = Query(None, description="Filtrer par ID de compétition"),
    equipe_id: Optional[int] = Query(None, description="Filtrer par ID d'équipe"),
    joueur_id: Optional[int] = Query(None, description="Filtrer par ID de joueur"),
    saison_id: Optional[int] = Query(None, description="Filtrer par ID de saison"),
    ligue: Optional[str] = Query(None, description="Filtrer par ligue/région"),
    departement: Optional[str] = Query(None, description="Filtrer par code département (ou liste séparée par virgule)"),
    departements: Optional[str] = Query(None, description="Alias pour liste de départements"),
    q: Optional[str] = Query(None, description="Recherche textuelle par mot-clé"),
    limit: int = Query(1000, ge=1, le=5000),
    session: Session = Depends(get_session),
) -> MapResponse:
    """Retourne les marqueurs géolocalisés pour la carte interactive.

    Gère le scoping contextuel (compétition, équipe, club, joueur, ligue, département)
    pour une expérience cartographique performante et ciblée.
    """
    if response:
        response.headers["Cache-Control"] = "public, max-age=60"

    markers: list[MapMarker] = []

    # Déballage défensif pour supporter les appels directs / tests unitaires
    def _to_str(val):
        return val if isinstance(val, str) else None

    def _to_int(val):
        return val if isinstance(val, int) else None

    entity_type = _to_str(entity_type)
    club_id = _to_int(club_id)
    competition_id = _to_int(competition_id)
    equipe_id = _to_int(equipe_id)
    joueur_id = _to_int(joueur_id)
    saison_id = _to_int(saison_id)
    ligue = _to_str(ligue)
    q_str = _to_str(q)
    limit = limit if isinstance(limit, int) else 1000

    raw_depts = _to_str(departement) or _to_str(departements) or ""
    dept_set: set[str] = set()
    for d in raw_depts.split(","):
        cleaned = d.strip().upper()
        if cleaned:
            if cleaned.isdigit() and len(cleaned) == 1:
                cleaned = cleaned.zfill(2)
            dept_set.add(cleaned)

    # ── Résolution du scope contextuel ──────────────────────────
    # Si on est sur une compétition, restreindre les clubs aux clubs participants
    scoped_club_ids: Optional[set[int]] = None
    if competition_id is not None:
        comp_club_ids = (
            session.query(EquipeDB.club_id)
            .filter(EquipeDB.competition_id == competition_id, EquipeDB.club_id.isnot(None))
            .distinct()
            .all()
        )
        scoped_club_ids = {c[0] for c in comp_club_ids if c[0] is not None}
    elif equipe_id is not None:
        eq_club_id = session.query(EquipeDB.club_id).filter(EquipeDB.id == equipe_id).scalar()
        scoped_club_ids = {eq_club_id} if eq_club_id else set()
    elif club_id is not None:
        scoped_club_ids = {club_id}

    # Déterminer quelles entités afficher selon le contexte
    req_entities: set[str] = set()
    if entity_type:
        for piece in entity_type.split(","):
            p_clean = piece.strip().lower()
            if p_clean:
                req_entities.add(p_clean)

    if req_entities:
        include_clubs = "club" in req_entities or "all" in req_entities
        include_salles = "salle" in req_entities or "all" in req_entities
        include_matchs = "match" in req_entities or "all" in req_entities
    else:
        include_clubs = True
        include_salles = True
        include_matchs = True

    # Si on est sur une fiche club et entity_type n'est pas spécifié,
    # on priorise le club et ses salles pour éviter d'inonder la carte de matchs.
    if club_id is not None and not req_entities:
        include_matchs = False

    # Si on est sur une fiche joueur et entity_type n'est pas spécifié,
    # on priorise les matchs joués.
    if joueur_id is not None and not req_entities:
        include_clubs = False
        include_salles = False
        include_matchs = True

    # ── 1. Marqueurs de Clubs ───────────────────────────────────
    if include_clubs:
        query = session.query(ClubDB).options(
            selectinload(ClubDB.salles),
            selectinload(ClubDB.equipes),
        )
        if scoped_club_ids is not None:
            query = query.filter(ClubDB.id.in_(scoped_club_ids))
        if ligue:
            query = query.filter(ClubDB.ligue == ligue)
        if dept_set:
            query = query.filter(ClubDB.departement.in_(dept_set))
        if q_str:
            query = query.filter(
                or_(
                    ClubDB.nom.ilike(f"%{q_str}%"),
                    ClubDB.ville.ilike(f"%{q_str}%"),
                )
            )

        for club in query.limit(limit).all():
            # Résolution précise : si le club n'a pas de lat/lng direct, chercher sa salle principale
            c_lat = club.latitude
            c_lng = club.longitude
            c_addr = None
            c_salles = getattr(club, "salles", []) or []
            if (c_lat is None or c_lng is None) and c_salles:
                main_salle = next((s for s in c_salles if s.numero == 1 and s.latitude is not None), None)
                if not main_salle:
                    main_salle = next((s for s in c_salles if s.latitude is not None), None)
                if main_salle:
                    c_lat = main_salle.latitude
                    c_lng = main_salle.longitude
                    c_addr = main_salle.adresse

            coords = resolve_entity_coordinates(
                latitude=c_lat,
                longitude=c_lng,
                ville=club.ville,
                adresse=c_addr,
                departement=club.departement,
                entity_id=club.id,
            )
            if coords is None:
                continue

            markers.append(
                MapMarker(
                    lat=coords[0],
                    lng=coords[1],
                    label=club.nom,
                    entity_type="club",
                    entity_id=club.id,
                    popup_html=_club_popup(club),
                    icon_color="blue",
                    icon_type="club",
                    sublabel=club.ville or club.departement or "Club",
                    departement=club.departement,
                    ville=club.ville,
                    url=f"/clubs/{club.id}",
                )
            )

    # ── 2. Marqueurs de Salles ──────────────────────────────────
    if include_salles:
        query = session.query(SalleClubDB).options(joinedload(SalleClubDB.club))
        if scoped_club_ids is not None:
            query = query.filter(SalleClubDB.club_id.in_(scoped_club_ids))
        if ligue or dept_set:
            query = query.join(ClubDB, SalleClubDB.club_id == ClubDB.id)
            if ligue:
                query = query.filter(ClubDB.ligue == ligue)
            if dept_set:
                query = query.filter(ClubDB.departement.in_(dept_set))
        if q_str:
            query = query.filter(
                or_(
                    SalleClubDB.nom.ilike(f"%{q_str}%"),
                    SalleClubDB.ville.ilike(f"%{q_str}%"),
                )
            )

        for salle in query.limit(limit).all():
            coords = resolve_entity_coordinates(
                latitude=salle.latitude,
                longitude=salle.longitude,
                ville=salle.ville or (salle.club.ville if salle.club else None),
                adresse=salle.adresse,
                departement=salle.club.departement if salle.club else None,
                entity_id=salle.id,
            )
            if coords is None:
                continue

            nom_salle = salle.nom or f"Salle {salle.numero}"
            salle_dept = salle.club.departement if salle.club else None
            salle_ville = salle.ville or (salle.club.ville if salle.club else None)
            markers.append(
                MapMarker(
                    lat=coords[0],
                    lng=coords[1],
                    label=nom_salle,
                    entity_type="salle",
                    entity_id=salle.id,
                    popup_html=_salle_popup(salle),
                    icon_color="cyan",
                    icon_type="salle",
                    sublabel=salle.ville or (salle.club.nom if salle.club else "Salle"),
                    departement=salle_dept,
                    ville=salle_ville,
                    url=f"/clubs/{salle.club_id}" if salle.club_id else None,
                )
            )

    # ── 3. Marqueurs de Matchs ──────────────────────────────────
    if include_matchs:
        query = (
            session.query(MatchDB)
            .join(EquipeDB, MatchDB.equipe_a_id == EquipeDB.id)
            .join(ClubDB, EquipeDB.club_id == ClubDB.id)
            .options(
                joinedload(MatchDB.equipe_a).joinedload(EquipeDB.club).joinedload(ClubDB.salles),
                joinedload(MatchDB.equipe_b),
                joinedload(MatchDB.competition),
                joinedload(MatchDB.sets),
            )
        )

        if competition_id is not None:
            query = query.filter(MatchDB.competition_id == competition_id)
        if equipe_id is not None:
            query = query.filter(
                or_(MatchDB.equipe_a_id == equipe_id, MatchDB.equipe_b_id == equipe_id)
            )
        if joueur_id is not None:
            query = query.join(
                ParticipationMatchDB, ParticipationMatchDB.match_id == MatchDB.id
            ).filter(ParticipationMatchDB.joueur_id == joueur_id)
        if saison_id is not None:
            query = query.filter(MatchDB.saison_id == saison_id)
        if club_id is not None:
            query = query.filter(EquipeDB.club_id == club_id)
        if ligue:
            query = query.filter(ClubDB.ligue == ligue)
        if dept_set:
            query = query.filter(ClubDB.departement.in_(dept_set))
        if q_str:
            query = query.filter(
                or_(
                    MatchDB.salle.ilike(f"%{q_str}%"),
                    EquipeDB.nom.ilike(f"%{q_str}%"),
                )
            )

        seen_match_ids: set[int] = set()
        for match in query.limit(limit).all():
            if match.id in seen_match_ids:
                continue
            seen_match_ids.add(match.id)

            lat = lng = None
            if match.equipe_a and match.equipe_a.club:
                club = match.equipe_a.club
                club_salles = getattr(club, "salles", []) or []

                # 1. Chercher si une salle correspond spécifiquement au nom match.salle
                matched_salle = None
                if match.salle and club_salles:
                    m_norm = match.salle.strip().lower()
                    for s in club_salles:
                        s_norm = (s.nom or "").strip().lower()
                        if s_norm and (s_norm in m_norm or m_norm in s_norm):
                            matched_salle = s
                            break

                if matched_salle:
                    c = resolve_entity_coordinates(
                        latitude=matched_salle.latitude,
                        longitude=matched_salle.longitude,
                        ville=matched_salle.ville or club.ville,
                        adresse=matched_salle.adresse,
                        departement=club.departement,
                        entity_id=matched_salle.id,
                    )
                    if c is not None:
                        lat, lng = c

                # 2. Sinon parcourir les salles déclarées du club receveur
                if lat is None:
                    for salle in club_salles:
                        c = resolve_entity_coordinates(
                            latitude=salle.latitude,
                            longitude=salle.longitude,
                            ville=salle.ville or club.ville,
                            adresse=salle.adresse,
                            departement=club.departement,
                            entity_id=salle.id,
                        )
                        if c is not None:
                            lat, lng = c
                            break

                # 3. Fallback sur le club receveur
                if lat is None:
                    c = resolve_entity_coordinates(
                        latitude=club.latitude,
                        longitude=club.longitude,
                        ville=club.ville,
                        adresse=None,
                        departement=club.departement,
                        entity_id=club.id,
                    )
                    if c is not None:
                        lat, lng = c

            if lat is not None and lng is not None:
                ea_nom = match.equipe_a.nom if match.equipe_a else "Équipe A"
                eb_nom = match.equipe_b.nom if match.equipe_b else "Équipe B"
                label = f"{ea_nom} vs {eb_nom}"

                # Déterminer la couleur de la punaise selon le résultat
                icon_color = "gold"
                icon_type = "match_pending"
                if match.match_joue and match.sets_equipe_a is not None and match.sets_equipe_b is not None:
                    winner_a = match.sets_equipe_a > match.sets_equipe_b
                    if equipe_id is not None:
                        team_won = (match.equipe_a_id == equipe_id and winner_a) or (
                            match.equipe_b_id == equipe_id and not winner_a
                        )
                        icon_color = "green" if team_won else "red"
                        icon_type = "match_win" if team_won else "match_loss"
                    else:
                        icon_color = "green" if winner_a else "blue"
                        icon_type = "match_win"

                date_label = match.date_match.strftime("%d/%m/%Y") if match.date_match else ""
                markers.append(
                    MapMarker(
                        lat=lat,
                        lng=lng,
                        label=label,
                        entity_type="match",
                        entity_id=match.id,
                        popup_html=_match_popup(match, perspective_team_id=equipe_id),
                        icon_color=icon_color,
                        icon_type=icon_type,
                        sublabel=date_label or (match.competition.nom if match.competition else ""),
                        departement=club.departement if club else None,
                        ville=club.ville if club else None,
                        url=f"/matchs/{match.id}",
                    )
                )

    # ── Calcul du centroïde et zoom ─────────────────────────────
    center_lat, center_lng, zoom = 46.6, 2.3, 6
    if markers:
        lats = [m.lat for m in markers]
        lngs = [m.lng for m in markers]
        center_lat = sum(lats) / len(lats)
        center_lng = sum(lngs) / len(lngs)
        lat_spread = max(lats) - min(lats)
        lng_spread = max(lngs) - min(lngs)
        spread = max(lat_spread, lng_spread)
        if spread < 0.05:
            zoom = 14
        elif spread < 0.2:
            zoom = 12
        elif spread < 1.0:
            zoom = 10
        elif spread < 3.0:
            zoom = 8
        else:
            zoom = 6

    return MapResponse(
        markers=markers,
        center_lat=center_lat,
        center_lng=center_lng,
        zoom=zoom,
    )
