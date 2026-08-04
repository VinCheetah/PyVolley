"""
Convertisseurs de modèles DB vers schémas Pydantic de réponse API.

Centralise la logique de transformation pour éviter la duplication
dans les différents modules de routes.
"""

from pyvolley.api.schemas import (
    MatchResponse,
    MatchDetail,
    SetDetailResponse,
    FormationResponse,
    ChangementResponse,
    TimeoutResponse,
    ParticipationResponse,
    ArbitreMatchResponse,
    OfficielResponse,
    SanctionResponse,
)


def match_to_response(m) -> MatchResponse:
    """Convertit un modèle DB Match en MatchResponse."""
    return MatchResponse(
        id=m.id,
        code_match=m.code_match,
        date=m.date_match,
        heure=m.heure_match,
        lieu=getattr(m, "lieu", None) or m.salle,
        equipe_a_nom=m.equipe_a.nom if m.equipe_a else "???",
        equipe_b_nom=m.equipe_b.nom if m.equipe_b else "???",
        score_sets=m.score_sets,
        score_export=getattr(m, "score_export", None),
        score_pdf=getattr(m, "score_pdf", None),
        score_effective=getattr(m, "score_effective", None),
        score_display=getattr(m, "score_display", None),
        score_conflict=bool(getattr(m, "score_conflict", False)),
        sets_equipe_a=m.sets_equipe_a,
        sets_equipe_b=m.sets_equipe_b,
        vainqueur=m.vainqueur,
        has_details=m.has_details,
        competition_nom=m.competition.nom if m.competition else None,
        genre=m.competition.genre if m.competition else None,
        categorie=m.competition.categorie if m.competition else None,
        journee=m.journee,
    )


def match_to_detail(match) -> MatchDetail:
    """Convertit un modèle DB Match (avec détails chargés) en MatchDetail."""
    sets_detail = []
    for s in match.sets or []:
        formations = [
            FormationResponse(
                equipe=f.equipe,
                position_1=f.position_1,
                position_2=f.position_2,
                position_3=f.position_3,
                position_4=f.position_4,
                position_5=f.position_5,
                position_6=f.position_6,
            )
            for f in (s.formations or [])
        ]
        changements = [
            ChangementResponse(
                equipe=c.equipe,
                joueur_entrant=c.joueur_entrant,
                joueur_sortant=c.joueur_sortant,
                position=c.position,
                score_a=c.score_a,
                score_b=c.score_b,
            )
            for c in (s.changements or [])
        ]
        timeouts = [
            TimeoutResponse(
                equipe=t.equipe, score_a=t.score_a, score_b=t.score_b
            )
            for t in (s.timeouts or [])
        ]
        sets_detail.append(
            SetDetailResponse(
                numero=s.numero,
                score_a=s.score_a or 0,
                score_b=s.score_b or 0,
                heure_debut=s.heure_debut,
                heure_fin=s.heure_fin,
                duree_minutes=s.duree_minutes,
                service_initial=s.service_initial,
                formations=formations,
                changements=changements,
                timeouts=timeouts,
            )
        )

    participations = [
        ParticipationResponse(
            joueur_id=p.joueur.id,
            joueur_nom=p.joueur.nom,
            joueur_prenom=p.joueur.prenom,
            joueur_licence=p.joueur.licence,
            equipe_nom=p.equipe.nom if p.equipe else "",
            equipe_id=p.equipe_id,
            numero_maillot=p.numero_maillot,
            est_capitaine=p.est_capitaine,
            est_libero=p.est_libero,
        )
        for p in (match.participations or [])
    ]

    arbitres_match = [
        ArbitreMatchResponse(
            arbitre_id=am.arbitre.id,
            nom=am.arbitre.nom,
            prenom=am.arbitre.prenom,
            role=am.role,
        )
        for am in (match.arbitrages or [])
    ]

    officiels = [
        OfficielResponse(
            role=o.role,
            nom=o.nom,
            prenom=o.prenom,
            licence=o.licence,
            equipe=o.equipe,
        )
        for o in (match.officiels or [])
    ]

    sanctions = [
        SanctionResponse(
            type_sanction=s.type_sanction,
            set_numero=s.set_numero,
            equipe=s.equipe,
            joueur_numero=s.joueur_numero,
            score_a=s.score_a,
            score_b=s.score_b,
        )
        for s in (match.sanctions or [])
    ]

    return MatchDetail(
        id=match.id,
        code_match=match.code_match,
        date=match.date_match,
        heure=match.heure_match,
        lieu=getattr(match, "lieu", None) or match.salle,
        salle=match.salle,
        equipe_a_nom=match.equipe_a.nom if match.equipe_a else "???",
        equipe_b_nom=match.equipe_b.nom if match.equipe_b else "???",
        equipe_a_id=match.equipe_a_id,
        equipe_b_id=match.equipe_b_id,
        score_sets=match.score_sets,
        score_export=getattr(match, "score_export", None),
        score_pdf=getattr(match, "score_pdf", None),
        score_effective=getattr(match, "score_effective", None),
        score_display=getattr(match, "score_display", None),
        score_conflict=bool(getattr(match, "score_conflict", False)),
        sets_equipe_a=match.sets_equipe_a,
        sets_equipe_b=match.sets_equipe_b,
        vainqueur=match.vainqueur,
        has_details=match.has_details,
        competition_nom=match.competition.nom if match.competition else None,
        genre=match.competition.genre if match.competition else None,
        categorie=match.competition.categorie if match.competition else None,
        division_code=match.competition.division if match.competition else None,
        saison_code=match.saison.code if match.saison else None,
        journee=match.journee,
        duree_totale=match.duree_totale,
        remarques=match.remarques,
        sets=sets_detail,
        participations=participations,
        arbitres=arbitres_match,
        officiels=officiels,
        sanctions=sanctions,
    )
