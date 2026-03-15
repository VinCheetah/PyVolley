"""
Convertisseur MatchDB → Match (modèle Pydantic core).

Reconstruit un objet Match à partir des données en base de données,
pour permettre l'utilisation des fonctions d'analyse.
"""

import logging
import hashlib
from datetime import time as datetime_time
from typing import Optional

from ..core.models import (
    Match, Set, SetTeamData, Formation, Joueur, Equipe,
    Changement, TimeOut, Sanction, TypeSanction,
    Arbitre, RoleArbitre, Officiel,
)
from ..database.models import (
    MatchDB, SetDB, FormationDB, ChangementDB, TimeoutDB,
    ParticipationMatchDB, SanctionDB, ArbitreMatchDB, OfficielMatchDB,
)

logger = logging.getLogger(__name__)


def _parse_heure(heure_str: Optional[str]) -> Optional[datetime_time]:
    """Parse une chaîne HH:MM ou HH:MM:SS en objet time."""
    if not heure_str:
        return None
    try:
        parts = heure_str.split(":")
        if len(parts) >= 2:
            return datetime_time(int(parts[0]), int(parts[1]),
                                 int(parts[2]) if len(parts) > 2 else 0)
    except (ValueError, IndexError):
        pass
    return None


def _sanitize_joueur_licence(licence: Optional[str]) -> str:
    """Normalise la licence pour respecter les contraintes du modèle core.

    Le modèle ``core.models.Joueur`` impose ``max_length=10``.
    Certaines anciennes licences synthétiques (ex: ``NL-xxxxxxxxxxxx``)
    peuvent dépasser cette longueur.
    """
    value = (licence or "").strip()
    if not value:
        return "0"
    if value.isdigit() and len(value) <= 10:
        return value
    if value.isdigit() and len(value) > 10:
        return value[-10:]

    # Fallback legacy pour licences synthétiques non numériques (ex: NL-...)
    # Convertit en clé numérique stable sur 10 chiffres.
    hash_int = int(hashlib.sha1(value.encode("utf-8")).hexdigest(), 16)
    return f"{hash_int % 10_000_000_000:010d}"


def match_db_to_core(
    match_db: MatchDB,
    participants_a: Optional[list[ParticipationMatchDB]] = None,
    participants_b: Optional[list[ParticipationMatchDB]] = None,
) -> Match:
    """Convertit un MatchDB (SQLAlchemy) en Match (Pydantic).

    Si ``participants_a`` et ``participants_b`` ne sont pas fournis,
    les participations sont automatiquement réparties depuis
    ``match_db.participations`` en fonction de l'équipe.

    Inclut les arbitres, officiels, remarques et heure du match.
    """
    # Auto-split des participations si non fournies
    if participants_a is None or participants_b is None:
        participants_a = []
        participants_b = []
        for p in (match_db.participations or []):
            if p.equipe_id == match_db.equipe_a_id:
                participants_a.append(p)
            elif p.equipe_id == match_db.equipe_b_id:
                participants_b.append(p)

    # Construire les équipes (avec officiels)
    officiels_a = [o for o in (match_db.officiels or []) if o.equipe == "A"]
    officiels_b = [o for o in (match_db.officiels or []) if o.equipe == "B"]
    equipe_a = _build_equipe(match_db, "A", participants_a, officiels_a)
    equipe_b = _build_equipe(match_db, "B", participants_b, officiels_b)

    # Construire les sets
    sets = [_build_set(s) for s in sorted(match_db.sets, key=lambda s: s.numero)]

    # Sanctions
    sanctions = [_build_sanction(s) for s in (match_db.sanctions or [])]

    # Arbitres
    arbitres = [_build_arbitre(am) for am in (match_db.arbitrages or [])]

    return Match(
        id=match_db.id,
        code_match=match_db.code_match,
        date=match_db.date_match,
        heure=_parse_heure(match_db.heure_match),
        lieu=match_db.salle,
        salle=match_db.salle,
        competition=match_db.competition.nom if match_db.competition else None,
        saison=match_db.saison.code if match_db.saison else None,
        journee=match_db.journee,
        equipe_a=equipe_a,
        equipe_b=equipe_b,
        equipe_a_id=match_db.equipe_a_id,
        equipe_b_id=match_db.equipe_b_id,
        vainqueur_nom=match_db.vainqueur,
        score_final=match_db.score_sets,
        sets_a=match_db.sets_equipe_a or 0,
        sets_b=match_db.sets_equipe_b or 0,
        duree_totale=match_db.duree_totale,
        match_joue=match_db.match_joue,
        has_details=match_db.has_details,
        sets=sets,
        sanctions=sanctions,
        arbitres=arbitres,
        remarques=match_db.remarques,
        source_pdf=match_db.source_pdf,
    )


def _build_equipe(
    match_db: MatchDB,
    side: str,
    participants: list[ParticipationMatchDB],
    officiels_db: Optional[list[OfficielMatchDB]] = None,
) -> Equipe:
    """Construit une Equipe à partir des participations et officiels."""
    equipe_db = match_db.equipe_a if side == "A" else match_db.equipe_b
    nom = equipe_db.nom if equipe_db else f"Équipe {side}"

    joueurs = []
    liberos = []
    for p in participants:
        j = Joueur(
            id=p.joueur_id,
            licence=_sanitize_joueur_licence(p.joueur.licence if p.joueur else None),
            nom=p.joueur.nom if p.joueur else "?",
            prenom=p.joueur.prenom if p.joueur else "",
            numero=p.numero_maillot,
            est_capitaine=p.est_capitaine,
            est_libero=p.est_libero,
        )
        joueurs.append(j)
        if p.est_libero:
            liberos.append(j)

    # Officiels d'équipe
    officials = []
    for off_db in (officiels_db or []):
        officials.append(Officiel(
            role=off_db.role,
            nom=off_db.nom,
            prenom=off_db.prenom,
            licence=off_db.licence,
        ))

    return Equipe(
        id=equipe_db.id if equipe_db else None,
        nom=nom,
        joueurs=joueurs,
        liberos=liberos,
        officiels=officials,
    )


def _build_set(set_db: SetDB) -> Set:
    """Construit un Set Pydantic à partir d'un SetDB."""
    # Désérialiser les données de services depuis JSON
    # Les clés str doivent être reconverties en int pour le modèle core
    services_a = {}
    services_b = {}
    if set_db.services_a:
        services_a = {int(k): v for k, v in set_db.services_a.items()}
    if set_db.services_b:
        services_b = {int(k): v for k, v in set_db.services_b.items()}

    equipe_a = SetTeamData(
        formation=_build_formation(set_db, "A"),
        changements=[_build_changement(c) for c in set_db.changements if c.equipe == "A"],
        timeouts=[_build_timeout(t) for t in set_db.timeouts if t.equipe == "A"],
        services=services_a,
    )
    equipe_b = SetTeamData(
        formation=_build_formation(set_db, "B"),
        changements=[_build_changement(c) for c in set_db.changements if c.equipe == "B"],
        timeouts=[_build_timeout(t) for t in set_db.timeouts if t.equipe == "B"],
        services=services_b,
    )

    return Set(
        id=set_db.id,
        numero=set_db.numero,
        score_a=set_db.score_a,
        score_b=set_db.score_b,
        duree_minutes=set_db.duree_minutes,
        service_initial=set_db.service_initial,
        equipe_a=equipe_a,
        equipe_b=equipe_b,
    )


def _build_formation(set_db: SetDB, side: str) -> Optional[Formation]:
    """Construit une Formation à partir d'un SetDB."""
    for f in (set_db.formations or []):
        if f.equipe == side:
            return Formation(
                position_1=f.position_1,
                position_2=f.position_2,
                position_3=f.position_3,
                position_4=f.position_4,
                position_5=f.position_5,
                position_6=f.position_6,
            )
    return None


def _build_changement(chg_db: ChangementDB) -> Changement:
    """Construit un Changement Pydantic."""
    return Changement(
        joueur_entrant=chg_db.joueur_entrant,
        joueur_sortant=chg_db.joueur_sortant,
        position=chg_db.position,
        score_a=chg_db.score_a,
        score_b=chg_db.score_b,
    )


def _build_timeout(to_db: TimeoutDB) -> TimeOut:
    """Construit un TimeOut Pydantic."""
    return TimeOut(score_a=to_db.score_a, score_b=to_db.score_b)


def _build_arbitre(am_db: ArbitreMatchDB) -> Arbitre:
    """Construit un Arbitre Pydantic depuis une association ArbitreMatchDB."""
    arb = am_db.arbitre
    # Convertir le rôle stocké en enum
    try:
        role = RoleArbitre(am_db.role)
    except ValueError:
        # Gérer les rôles stockés sous forme "arbitre_1", "arbitre_2"
        if "1" in am_db.role:
            role = RoleArbitre.PREMIER
        elif "2" in am_db.role:
            role = RoleArbitre.SECOND
        else:
            role = RoleArbitre.PREMIER

    return Arbitre(
        id=arb.id,
        licence=arb.licence,
        nom=arb.nom,
        prenom=arb.prenom,
        ligue=arb.ligue,
        role=role,
    )


def _build_sanction(s_db: SanctionDB) -> Sanction:
    """Construit une Sanction Pydantic."""
    try:
        type_sanction = TypeSanction(s_db.type_sanction)
    except ValueError:
        logger.warning(
            "Type de sanction invalide '%s' pour sanction id=%s, "
            "fallback vers AVERTISSEMENT",
            s_db.type_sanction, s_db.id,
        )
        type_sanction = TypeSanction.AVERTISSEMENT
    except ValueError:
        type_sanction = TypeSanction.AVERTISSEMENT

    return Sanction(
        type=type_sanction,
        set_numero=s_db.set_numero,
        equipe=s_db.equipe,
        joueur_numero=s_db.joueur_numero,
        score_a=s_db.score_a,
        score_b=s_db.score_b,
    )
