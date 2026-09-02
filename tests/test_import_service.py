"""Tests complets du MatchImportService — import de matchs parsés en base."""

import pytest
from sqlalchemy import select

from pyvolley.core.models import (
    Match, Equipe, Joueur, Set, SetTeamData, Formation,
    Changement, TimeOut, Arbitre, Sanction, Officiel,
    RoleArbitre, TypeSanction,
)
from pyvolley.database.import_service import MatchImportService
from pyvolley.database.models import (
    JoueurDB, MatchDB, SetDB, FormationDB, ChangementDB, TimeoutDB,
    OfficielMatchDB, PersonneDB, ArbitreDB, ArbitreMatchDB,
    SanctionDB, ParticipationMatchDB, SaisonDB, CompetitionDB,
    PouleDB, ClubDB, EquipeDB, JoueurMatchStatsDB,
)


# ============== Tests d'import basique ==============


class TestBasicImport:
    """Tests d'import de matchs simples."""

    def test_import_match_minimal(self, test_session):
        """Un match avec le minimum de données est importé correctement."""
        service = MatchImportService(test_session)
        match = Match(
            code_match="MIN001",
            equipe_a=Equipe(nom="Equipe AA", joueurs=[], liberos=[]),
            equipe_b=Equipe(nom="Equipe BB", joueurs=[], liberos=[]),
        )
        result = service.import_match(match)
        test_session.flush()

        assert result is not None
        assert result.code_match == "MIN001"
        assert result.equipe_a_id is not None
        assert result.equipe_b_id is not None

    def test_import_match_complet(self, test_session, full_match):
        """Un match complet avec tous les détails est importé correctement."""
        service = MatchImportService(test_session)
        result = service.import_match(full_match)
        test_session.flush()

        assert result is not None
        assert result.code_match == "TST-FULL-001"
        assert result.match_joue is True
        assert result.has_details is True
        assert result.vainqueur == "AS Volley Paris"
        assert result.score_sets == "3/0"
        assert result.sets_equipe_a == 3
        assert result.sets_equipe_b == 0
        assert result.duree_totale == "1h15"
        assert result.remarques == "Match test complet"
        assert result.salle == "Gymnase Central"

    def test_import_creates_saison(self, test_session, full_match):
        """L'import crée automatiquement la saison."""
        service = MatchImportService(test_session)
        service.import_match(full_match)
        test_session.flush()

        saison = test_session.scalar(select(SaisonDB).where(SaisonDB.code == "2024-2025"))
        assert saison is not None
        assert saison.nom == "Saison 2024-2025"

    def test_import_creates_competition(self, test_session, full_match):
        """L'import crée automatiquement la compétition."""
        service = MatchImportService(test_session)
        service.import_match(full_match)
        test_session.flush()

        comp = test_session.scalar(
            select(CompetitionDB).where(
                CompetitionDB.nom == "EMA - ELITE MASCULINE - POULE A"
            )
        )
        assert comp is not None
        assert comp.saison_id is not None

    def test_import_creates_clubs(self, test_session, full_match):
        """L'import crée les clubs correspondant aux équipes."""
        service = MatchImportService(test_session)
        service.import_match(full_match)
        test_session.flush()

        clubs = test_session.scalars(select(ClubDB)).all()
        assert len(clubs) >= 2

    def test_import_creates_equipes(self, test_session, full_match):
        """L'import crée les deux équipes."""
        service = MatchImportService(test_session)
        service.import_match(full_match)
        test_session.flush()

        equipes = test_session.scalars(select(EquipeDB)).all()
        noms = [e.nom for e in equipes]
        assert "AS Volley Paris" in noms
        assert "BC Volley Lyon" in noms


# ============== Tests d'import des sets ==============


class TestSetImport:
    """Tests d'import des sets avec formations, changements, timeouts."""

    def test_sets_are_imported(self, test_session, full_match):
        """Les 3 sets sont importés avec les scores corrects."""
        service = MatchImportService(test_session)
        result = service.import_match(full_match)
        test_session.flush()

        sets = test_session.scalars(
            select(SetDB).where(SetDB.match_id == result.id).order_by(SetDB.numero)
        ).all()
        assert len(sets) == 3
        assert sets[0].score_a == 25 and sets[0].score_b == 22
        assert sets[1].score_a == 25 and sets[1].score_b == 20
        assert sets[2].score_a == 25 and sets[2].score_b == 18

    def test_formations_are_imported(self, test_session, full_match):
        """Les formations de départ du set 1 sont importées."""
        service = MatchImportService(test_session)
        result = service.import_match(full_match)
        test_session.flush()

        set1 = test_session.scalar(
            select(SetDB).where(SetDB.match_id == result.id, SetDB.numero == 1)
        )
        formations = test_session.scalars(
            select(FormationDB).where(FormationDB.set_id == set1.id)
        ).all()
        assert len(formations) == 2  # Une pour chaque équipe

        form_a = next(f for f in formations if f.equipe == "A")
        assert form_a.position_1 == "1"
        assert form_a.position_2 == "4"
        assert form_a.position_3 == "7"

    def test_changements_are_imported(self, test_session, full_match):
        """Les changements du set 1 sont importés."""
        service = MatchImportService(test_session)
        result = service.import_match(full_match)
        test_session.flush()

        set1 = test_session.scalar(
            select(SetDB).where(SetDB.match_id == result.id, SetDB.numero == 1)
        )
        chgs = test_session.scalars(
            select(ChangementDB).where(ChangementDB.set_id == set1.id)
        ).all()
        assert len(chgs) == 1
        assert chgs[0].joueur_entrant == "2"
        assert chgs[0].joueur_sortant == "13"
        assert chgs[0].score_a == 15

    def test_timeouts_are_imported(self, test_session, full_match):
        """Les timeouts du set 1 sont importés."""
        service = MatchImportService(test_session)
        result = service.import_match(full_match)
        test_session.flush()

        set1 = test_session.scalar(
            select(SetDB).where(SetDB.match_id == result.id, SetDB.numero == 1)
        )
        timeouts = test_session.scalars(
            select(TimeoutDB).where(TimeoutDB.set_id == set1.id)
        ).all()
        assert len(timeouts) == 2  # Un par équipe

    def test_set_metadata(self, test_session, full_match):
        """Les métadonnées de set (durée, service initial) sont importées."""
        service = MatchImportService(test_session)
        result = service.import_match(full_match)
        test_session.flush()

        set1 = test_session.scalar(
            select(SetDB).where(SetDB.match_id == result.id, SetDB.numero == 1)
        )
        assert set1.duree_minutes == 28
        assert set1.service_initial == "A"


# ============== Tests de joueurs ==============


class TestJoueurImport:
    """Tests d'import et de déduplication des joueurs."""

    def test_joueurs_are_imported(self, test_session, full_match):
        """Tous les joueurs (y compris libéros) sont importés."""
        service = MatchImportService(test_session)
        result = service.import_match(full_match)
        test_session.flush()

        participations = test_session.scalars(
            select(ParticipationMatchDB).where(
                ParticipationMatchDB.match_id == result.id
            )
        ).all()
        # 7 joueurs équipe A + 7 joueurs équipe B = 14
        assert len(participations) == 14

    def test_missing_or_zero_licence_does_not_merge_all_players(self, test_session):
        """Les joueurs avec licence '0' reçoivent chacun une licence synthétique unique."""
        service = MatchImportService(test_session)
        match = Match(
            code_match="TST001",
            equipe_a=Equipe(
                nom="Equipe A",
                joueurs=[
                    Joueur(numero="1", nom="DUPONT", prenom="Jean", licence="0"),
                    Joueur(numero="2", nom="MARTIN", prenom="Paul", licence="0"),
                ],
                liberos=[],
            ),
            equipe_b=Equipe(nom="Equipe B", joueurs=[], liberos=[]),
        )
        service.import_match(match)
        test_session.flush()

        joueurs = test_session.scalars(select(JoueurDB).order_by(JoueurDB.id)).all()
        assert len(joueurs) == 2
        assert joueurs[0].licence.isdigit()
        assert joueurs[1].licence.isdigit()
        assert len(joueurs[0].licence) <= 10
        assert len(joueurs[1].licence) <= 10
        assert joueurs[0].licence != joueurs[1].licence

    def test_joueur_deduplication_by_licence(self, test_session):
        """Un joueur avec la même licence dans deux matchs n'est créé qu'une fois."""
        service = MatchImportService(test_session)
        for i, code in enumerate(["DEDUP01", "DEDUP02"]):
            match = Match(
                code_match=code,
                equipe_a=Equipe(
                    nom=f"Equipe Alpha {i}",
                    joueurs=[Joueur(numero="1", nom="SAME", prenom="Player", licence="555555")],
                    liberos=[],
                ),
                equipe_b=Equipe(nom=f"Equipe Beta {i}", joueurs=[], liberos=[]),
            )
            service.import_match(match)
        test_session.flush()

        joueurs = test_session.scalars(
            select(JoueurDB).where(JoueurDB.licence == "555555")
        ).all()
        assert len(joueurs) == 1

    def test_libero_not_duplicated(self, test_session):
        """Un libéro présent dans `joueurs` et `liberos` n'a qu'une participation."""
        service = MatchImportService(test_session)
        libero = Joueur(numero="2", nom="LIBERO", prenom="Test", licence="001001", est_libero=True)
        match = Match(
            code_match="LIBDUP01",
            equipe_a=Equipe(
                nom="Equipe Alpha",
                joueurs=[
                    Joueur(numero="1", nom="PLAYER", prenom="A", licence="001002"),
                    libero,
                ],
                liberos=[libero],
            ),
            equipe_b=Equipe(nom="Equipe Beta", joueurs=[], liberos=[]),
        )
        result = service.import_match(match)
        test_session.flush()

        parts = test_session.scalars(
            select(ParticipationMatchDB).where(
                ParticipationMatchDB.match_id == result.id
            )
        ).all()
        # 2 joueurs uniques, pas 3
        assert len(parts) == 2

    def test_joueur_linked_to_personne(self, test_session):
        """Chaque joueur importé est lié à une PersonneDB."""
        service = MatchImportService(test_session)
        match = Match(
            code_match="PERS01",
            equipe_a=Equipe(
                nom="Equipe Alpha",
                joueurs=[Joueur(numero="1", nom="PERSONNAGE", prenom="Test", licence="900001")],
                liberos=[],
            ),
            equipe_b=Equipe(nom="Equipe Beta", joueurs=[], liberos=[]),
        )
        service.import_match(match)
        test_session.flush()

        joueur = test_session.scalar(select(JoueurDB).where(JoueurDB.licence == "900001"))
        assert joueur.personne_id is not None

    def test_joueur_match_stats_persisted_on_detailed_import(self, test_session, full_match):
        """Un import détaillé persiste des stats joueur par match en base."""
        service = MatchImportService(test_session)
        result = service.import_match(full_match)
        test_session.flush()

        stats_rows = test_session.scalars(
            select(JoueurMatchStatsDB).where(JoueurMatchStatsDB.match_id == result.id)
        ).all()
        assert len(stats_rows) >= 10
        assert all(r.side in ("A", "B") for r in stats_rows)
        assert all(r.points_gagnes is not None for r in stats_rows)

    def test_compute_player_stats_clears_orphan_rows_when_no_participants(self, test_session):
        """Le calcul purge les stats existantes si le match n'a plus de participants exploitables."""
        from pyvolley.database.player_stats_service import JoueurMatchStatsService

        saison = SaisonDB(code="2025-2026", nom="Saison 2025-2026")
        competition = CompetitionDB(nom="Comp test", saison=saison)
        joueur = JoueurDB(licence="L-ORPHAN", nom="ORPHAN", prenom="Row")
        match = MatchDB(
            code_match="ORPHAN-001",
            saison=saison,
            competition=competition,
            has_details=True,
        )
        test_session.add_all([saison, competition, joueur, match])
        test_session.flush()

        stale_row = JoueurMatchStatsDB(
            match_id=match.id,
            joueur_id=joueur.id,
            equipe_id=None,
            side="A",
            points_gagnes=1,
            points_perdus=0,
            points_joues=1,
            points_gagnes_service=0,
            services=0,
            series=0,
            max_serie=0,
            moyenne_services_par_serie=0.0,
            ratio_points_gagnes=1.0,
            match_updated_at=match.updated_at,
        )
        test_session.add(stale_row)
        test_session.commit()

        service = JoueurMatchStatsService(test_session)
        written = service.compute_and_store_for_match(match, force=True)
        test_session.flush()

        rows_after = test_session.scalars(
            select(JoueurMatchStatsDB).where(JoueurMatchStatsDB.match_id == match.id)
        ).all()
        assert written == 0
        assert rows_after == []


# ============== Tests d'officiels et arbitres ==============


class TestOfficielsArbitres:
    """Tests pour l'import des officiels d'équipe et arbitres."""

    def test_officiels_are_linked_to_personnes(self, test_session):
        """Les officiels (coachs) sont liés à des PersonneDB."""
        service = MatchImportService(test_session)
        match = Match(
            code_match="TST002",
            equipe_a=Equipe(
                nom="Equipe A",
                joueurs=[],
                liberos=[],
                officiels=[Officiel(role="EA", nom="COACH", prenom="Alice", licence="998877")],
            ),
            equipe_b=Equipe(
                nom="Equipe B",
                joueurs=[],
                liberos=[],
                officiels=[Officiel(role="EB", nom="MANAGER", prenom="Bob", licence=None)],
            ),
        )
        service.import_match(match)
        test_session.flush()

        officiels = test_session.scalars(
            select(OfficielMatchDB).order_by(OfficielMatchDB.id)
        ).all()
        assert len(officiels) == 2
        assert officiels[0].personne_id is not None
        assert officiels[1].personne_id is not None

        personnes = test_session.scalars(select(PersonneDB)).all()
        assert len(personnes) >= 2

    def test_arbitres_are_imported(self, test_session, full_match):
        """Les arbitres du match sont importés avec leur rôle."""
        service = MatchImportService(test_session)
        result = service.import_match(full_match)
        test_session.flush()

        arbitrages = test_session.scalars(
            select(ArbitreMatchDB).where(ArbitreMatchDB.match_id == result.id)
        ).all()
        assert len(arbitrages) == 2

        arbitres = test_session.scalars(select(ArbitreDB)).all()
        assert len(arbitres) == 2
        licences = {a.licence for a in arbitres}
        assert "ARB001" in licences
        assert "ARB002" in licences

    def test_sanctions_are_imported(self, test_session, full_match):
        """Les sanctions sont importées avec les bons détails."""
        service = MatchImportService(test_session)
        result = service.import_match(full_match)
        test_session.flush()

        sanctions = test_session.scalars(
            select(SanctionDB).where(SanctionDB.match_id == result.id)
        ).all()
        assert len(sanctions) == 1
        assert sanctions[0].type_sanction == "A"
        assert sanctions[0].equipe == "B"
        assert sanctions[0].joueur_numero == "5"
        assert sanctions[0].set_numero == 2


# ============== Tests de doublons ==============


class TestDuplicateHandling:
    """Tests de gestion des doublons."""

    def test_duplicate_match_is_skipped(self, test_session, full_match):
        """Un import en double du même match retourne None."""
        service = MatchImportService(test_session)
        result1 = service.import_match(full_match)
        test_session.flush()
        result2 = service.import_match(full_match)

        assert result1 is not None
        assert result2 is None

    def test_import_matches_batch_stats(self, test_session):
        """import_matches retourne des statistiques correctes."""
        service = MatchImportService(test_session)
        matches = [
            Match(
                code_match=f"BATCH{i:03d}",
                equipe_a=Equipe(nom=f"Equipe Alpha {i}", joueurs=[], liberos=[]),
                equipe_b=Equipe(nom=f"Equipe Beta {i}", joueurs=[], liberos=[]),
            )
            for i in range(5)
        ]
        stats = service.import_matches(matches, batch_size=3)
        assert stats["total"] == 5
        assert stats["imported"] == 5
        assert stats["committed"] == 5
        assert stats["duplicates"] == 0
        assert len(stats["errors"]) == 0

    def test_import_matches_detects_duplicates(self, test_session):
        """import_matches détecte les doublons dans le même batch."""
        service = MatchImportService(test_session)
        match = Match(
            code_match="DUP001",
            equipe_a=Equipe(nom="Equipe Alpha", joueurs=[], liberos=[]),
            equipe_b=Equipe(nom="Equipe Beta", joueurs=[], liberos=[]),
        )
        # Premier import
        service.import_match(match)
        test_session.commit()
        service.clear_caches()

        # Deuxième import via batch
        stats = service.import_matches([match])
        assert stats["duplicates"] == 1
        assert stats["imported"] == 0


# ============== Tests d'enrichissement ==============


class TestEnrichFromPDF:
    """Tests de la méthode enrich_from_pdf (Phase 2 du pipeline)."""

    def test_enrich_adds_details(self, test_session):
        """L'enrichissement ajoute les détails d'un PDF à un match existant."""
        service = MatchImportService(test_session)

        # Créer un match basique (comme depuis Phase 1)
        basic_match = Match(
            code_match="ENRICH01",
            equipe_a=Equipe(nom="Club Alpha", joueurs=[], liberos=[]),
            equipe_b=Equipe(nom="Club Beta", joueurs=[], liberos=[]),
            match_joue=True,
        )
        match_db = service.import_match(basic_match)
        test_session.flush()
        match_db.parsing_status = "downloaded"  # Simuler Phase 1
        match_db.has_details = False
        test_session.flush()

        # Enrichir avec des données PDF détaillées
        parsed = Match(
            code_match="ENRICH01",
            equipe_a=Equipe(
                nom="Club Alpha",
                joueurs=[Joueur(numero="1", nom="JOUEUR", prenom="A", licence="100099")],
                liberos=[],
            ),
            equipe_b=Equipe(nom="Club Beta", joueurs=[], liberos=[]),
            sets=[Set(numero=1, score_a=25, score_b=20)],
            vainqueur_nom="Club Alpha",
            score_final="3-0",
            duree_totale="1h00",
            remarques="Notes du PDF",
        )

        was_enriched = service.enrich_from_pdf(match_db, parsed)
        test_session.flush()

        assert was_enriched is True
        assert match_db.parsing_status == "parsed"
        assert match_db.has_details is True
        assert match_db.vainqueur == "Club Alpha"
        assert match_db.remarques == "Notes du PDF"

        # Vérifier que les sets ont été créés
        sets = test_session.scalars(
            select(SetDB).where(SetDB.match_id == match_db.id)
        ).all()
        assert len(sets) == 1
        assert sets[0].score_a == 25

        # Vérifier la persistance des stats détaillées joueur
        stats_rows = test_session.scalars(
            select(JoueurMatchStatsDB).where(JoueurMatchStatsDB.match_id == match_db.id)
        ).all()
        assert len(stats_rows) == 1
        assert stats_rows[0].joueur.licence == "100099"

    def test_enrich_does_not_overwrite_parsed(self, test_session):
        """L'enrichissement ne re-traite pas un match déjà parsé (sans force)."""
        service = MatchImportService(test_session)
        basic_match = Match(
            code_match="ENRICH02",
            equipe_a=Equipe(nom="Club Alpha", joueurs=[], liberos=[]),
            equipe_b=Equipe(nom="Club Beta", joueurs=[], liberos=[]),
        )
        match_db = service.import_match(basic_match)
        test_session.flush()
        # Simuler un match déjà parsé
        match_db.parsing_status = "parsed"
        match_db.has_details = True
        test_session.flush()

        parsed = Match(
            code_match="ENRICH02",
            equipe_a=Equipe(nom="Club Alpha", joueurs=[], liberos=[]),
            equipe_b=Equipe(nom="Club Beta", joueurs=[], liberos=[]),
        )
        was_enriched = service.enrich_from_pdf(match_db, parsed)
        assert was_enriched is False

    def test_enrich_with_force(self, test_session):
        """Avec force=True, l'enrichissement re-traite un match déjà parsé."""
        service = MatchImportService(test_session)
        basic_match = Match(
            code_match="ENRICH03",
            equipe_a=Equipe(nom="Club Alpha", joueurs=[], liberos=[]),
            equipe_b=Equipe(nom="Club Beta", joueurs=[], liberos=[]),
        )
        match_db = service.import_match(basic_match)
        test_session.flush()
        match_db.parsing_status = "parsed"
        match_db.has_details = True
        test_session.flush()

        parsed = Match(
            code_match="ENRICH03",
            equipe_a=Equipe(nom="Club Alpha", joueurs=[], liberos=[]),
            equipe_b=Equipe(nom="Club Beta", joueurs=[], liberos=[]),
            sets=[Set(numero=1, score_a=25, score_b=15)],
            remarques="Forcé",
        )
        was_enriched = service.enrich_from_pdf(match_db, parsed, force=True)
        assert was_enriched is True
        assert match_db.remarques == "Forcé"
