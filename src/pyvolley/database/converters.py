"""
Convertisseur MatchDB → Match (modèle Pydantic core).

Reconstruit un objet Match à partir des données en base de données,
pour permettre l'utilisation des fonctions d'analyse.
"""

from typing import Optional

from ..core.models import (
    Match, Set, SetTeamData, Formation, Joueur, Equipe,
    Changement, TimeOut, Sanction, TypeSanction,
)
from ..database.models import (
    MatchDB, SetDB, FormationDB, ChangementDB, TimeoutDB,
    ParticipationMatchDB, SanctionDB,
)


def match_db_to_core(
    match_db: MatchDB,
    participants_a: list[ParticipationMatchDB],
    participants_b: list[ParticipationMatchDB],
) -> Match:
    """Convertit un MatchDB (SQLAlchemy) en Match (Pydantic).

    Note : les données de services (scores à la perte de
    service par position) ne sont pas stockées en BDD.
    Les ServiceStats seront donc vides.
    """
    # Construire les équipes
    equipe_a = _build_equipe(match_db, "A", participants_a)
    equipe_b = _build_equipe(match_db, "B", participants_b)

    # Construire les sets
    sets = [_build_set(s) for s in sorted(match_db.sets, key=lambda s: s.numero)]

    # Sanctions
    sanctions = [_build_sanction(s) for s in (match_db.sanctions or [])]

    return Match(
        id=match_db.id,
        code_match=match_db.code_match,
        date=match_db.date_match,
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
        source_pdf=match_db.source_pdf,
    )


def _build_equipe(
    match_db: MatchDB,
    side: str,
    participants: list[ParticipationMatchDB],
) -> Equipe:
    """Construit une Equipe à partir des participations."""
    equipe_db = match_db.equipe_a if side == "A" else match_db.equipe_b
    nom = equipe_db.nom if equipe_db else f"Équipe {side}"

    joueurs = []
    liberos = []
    for p in participants:
        j = Joueur(
            id=p.joueur_id,
            licence=p.joueur.licence if p.joueur else "0",
            nom=p.joueur.nom if p.joueur else "?",
            prenom=p.joueur.prenom if p.joueur else "",
            numero=p.numero_maillot,
            est_capitaine=p.est_capitaine,
            est_libero=p.est_libero,
        )
        joueurs.append(j)
        if p.est_libero:
            liberos.append(j)

    return Equipe(
        id=equipe_db.id if equipe_db else None,
        nom=nom,
        joueurs=joueurs,
        liberos=liberos,
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


def _build_sanction(s_db: SanctionDB) -> Sanction:
    """Construit une Sanction Pydantic."""
    try:
        type_sanction = TypeSanction(s_db.type_sanction)
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
