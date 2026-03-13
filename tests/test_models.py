"""Tests pour les modèles Pydantic — validation, propriétés, cas limites."""

import pytest
from pydantic import ValidationError

from pyvolley.core.models import (
    Joueur, Equipe, Set, Match, Formation, Changement, TimeOut,
    SetTeamData, Arbitre, Officiel, Sanction, Club,
    RoleArbitre, TypeSanction,
)


# ============== Joueur ==============


class TestJoueur:
    """Tests pour le modèle Joueur."""

    def test_creation_valide(self):
        joueur = Joueur(numero="7", nom="DUPONT", prenom="Jean", licence="123456789")
        assert joueur.numero == "7"
        assert joueur.nom == "DUPONT"
        assert joueur.prenom == "Jean"
        assert joueur.licence == "123456789"
        assert joueur.est_capitaine is False
        assert joueur.est_libero is False

    def test_joueur_capitaine(self):
        joueur = Joueur(numero="1", nom="MARTIN", prenom="Pierre", licence="123456", est_capitaine=True)
        assert joueur.est_capitaine is True

    def test_joueur_libero(self):
        joueur = Joueur(numero="2", nom="LIB", prenom="Ero", licence="654321", est_libero=True)
        assert joueur.est_libero is True

    def test_joueur_nom_complet(self):
        joueur = Joueur(numero="5", nom="DURAND", prenom="Marie", licence="987654321")
        assert joueur.nom_complet == "DURAND Marie"

    def test_licence_non_numerique_invalide(self):
        """Une licence non-numérique lève une ValidationError."""
        with pytest.raises(ValidationError, match="chiffres"):
            Joueur(numero="1", nom="TEST", prenom="A", licence="ABCDEF")

    def test_licence_vide_invalide(self):
        """Une licence vide lève une ValidationError."""
        with pytest.raises(ValidationError):
            Joueur(numero="1", nom="TEST", prenom="A", licence="")

    def test_nom_vide_invalide(self):
        """Un nom vide lève une ValidationError."""
        with pytest.raises(ValidationError):
            Joueur(numero="1", nom="", prenom="A", licence="123456")

    def test_prenom_vide_invalide(self):
        """Un prénom vide lève une ValidationError."""
        with pytest.raises(ValidationError):
            Joueur(numero="1", nom="TEST", prenom="", licence="123456")


# ============== Set ==============


class TestSet:
    """Tests pour le modèle Set."""

    def test_set_valide(self):
        s = Set(numero=1, score_a=25, score_b=23)
        assert s.numero == 1
        assert s.score_a == 25
        assert s.score_b == 23

    def test_set_vainqueur_a(self):
        assert Set(numero=1, score_a=25, score_b=23).vainqueur == "A"

    def test_set_vainqueur_b(self):
        assert Set(numero=2, score_a=20, score_b=25).vainqueur == "B"

    def test_set_vainqueur_none(self):
        assert Set(numero=3, score_a=None, score_b=None).vainqueur is None

    def test_set_score_str(self):
        assert Set(numero=1, score_a=25, score_b=18).score_str == "25-18"

    def test_set_numero_invalide_zero(self):
        with pytest.raises(ValidationError):
            Set(numero=0, score_a=25, score_b=20)

    def test_set_numero_invalide_trop_grand(self):
        with pytest.raises(ValidationError):
            Set(numero=6, score_a=25, score_b=20)

    def test_set_score_negatif_invalide(self):
        with pytest.raises(ValidationError):
            Set(numero=1, score_a=-1, score_b=20)

    def test_set_team_data(self):
        """La méthode team_data retourne le bon côté."""
        data_a = SetTeamData()
        data_b = SetTeamData()
        s = Set(numero=1, score_a=25, score_b=20, equipe_a=data_a, equipe_b=data_b)
        assert s.team_data("A") is data_a
        assert s.team_data("B") is data_b
        assert s.team_data("C") is None


# ============== Formation ==============


class TestFormation:
    """Tests pour le modèle Formation."""

    def test_formation_complete(self):
        f = Formation(
            position_1="1", position_2="4", position_3="7",
            position_4="10", position_5="13", position_6="16",
        )
        assert f.as_list() == ["1", "4", "7", "10", "13", "16"]

    def test_formation_dict(self):
        f = Formation(position_1="1", position_2="4", position_3="7",
                      position_4="10", position_5="13", position_6="16")
        d = f.as_dict()
        assert d["I"] == "1"
        assert d["VI"] == "16"

    def test_formation_vide(self):
        f = Formation()
        assert all(p is None for p in f.as_list())


# ============== Changement & TimeOut ==============


class TestChangement:
    def test_changement_complet(self):
        c = Changement(joueur_entrant="2", joueur_sortant="13", position=4, score_a=15, score_b=10)
        assert c.joueur_entrant == "2"
        assert c.joueur_sortant == "13"
        assert c.position == 4

    def test_changement_minimal(self):
        c = Changement(joueur_entrant="5")
        assert c.joueur_sortant is None
        assert c.position is None


class TestTimeOut:
    def test_timeout(self):
        t = TimeOut(score_a=10, score_b=8)
        assert t.score_a == 10
        assert t.score_b == 8


# ============== SetTeamData ==============


class TestSetTeamData:
    def test_nb_changements(self):
        data = SetTeamData(changements=[
            Changement(joueur_entrant="1"),
            Changement(joueur_entrant="2"),
        ])
        assert data.nb_changements == 2

    def test_nb_timeouts(self):
        data = SetTeamData(timeouts=[TimeOut(score_a=10, score_b=8)])
        assert data.nb_timeouts == 1

    def test_nb_services(self):
        data = SetTeamData(services={1: [0, 5, 10], 7: [15, 20]})
        assert data.nb_services == 5

    def test_empty(self):
        data = SetTeamData()
        assert data.nb_changements == 0
        assert data.nb_timeouts == 0
        assert data.nb_services == 0


# ============== Equipe ==============


class TestEquipe:
    """Tests pour le modèle Equipe."""

    def test_equipe_valide(self):
        joueur = Joueur(numero="1", nom="TEST", prenom="Test", licence="123456")
        equipe = Equipe(nom="AS Volley", joueurs=[joueur], liberos=[])
        assert equipe.nom == "AS Volley"
        assert len(equipe.joueurs) == 1

    def test_equipe_vide(self):
        equipe = Equipe(nom="Empty Team", joueurs=[], liberos=[])
        assert len(equipe.joueurs) == 0

    def test_equipe_nom_trop_court(self):
        with pytest.raises(ValidationError):
            Equipe(nom="A", joueurs=[], liberos=[])


# ============== Arbitre ==============


class TestArbitre:
    def test_arbitre_complet(self):
        a = Arbitre(nom="SMITH", prenom="John", licence="ARB001", role=RoleArbitre.PREMIER)
        assert a.nom_complet == "SMITH John"
        assert a.role == RoleArbitre.PREMIER

    def test_arbitre_sans_prenom(self):
        a = Arbitre(nom="SMITH")
        assert a.nom_complet == "SMITH"

    def test_role_par_defaut(self):
        assert Arbitre(nom="X").role == RoleArbitre.PREMIER


# ============== Officiel ==============


class TestOfficiel:
    def test_officiel_complet(self):
        o = Officiel(role="EA", nom="COACH", prenom="Alice", licence="998877")
        assert o.nom_complet == "COACH Alice"
        assert o.role == "EA"

    def test_officiel_sans_prenom(self):
        o = Officiel(role="EB", nom="MANAGER")
        assert o.nom_complet == "MANAGER"


# ============== Sanction ==============


class TestSanction:
    def test_sanction_avertissement(self):
        s = Sanction(type=TypeSanction.AVERTISSEMENT, set_numero=1, equipe="A", joueur_numero="5")
        assert s.type == TypeSanction.AVERTISSEMENT
        assert s.equipe == "A"

    @pytest.mark.parametrize("sanction_type", list(TypeSanction))
    def test_tous_types_valides(self, sanction_type):
        s = Sanction(type=sanction_type, set_numero=1, equipe="B")
        assert s.type == sanction_type

    def test_set_numero_invalide(self):
        with pytest.raises(ValidationError):
            Sanction(type=TypeSanction.AVERTISSEMENT, set_numero=0, equipe="A")


# ============== Match ==============


class TestMatch:
    """Tests pour le modèle Match."""

    def test_match_valide(self, sample_match):
        assert sample_match.code_match == "2024-R1-001"
        assert sample_match.vainqueur_nom == "AS Volley Club"
        assert sample_match.score_final == "3-0"

    def test_match_avec_sets(self, sample_match):
        assert len(sample_match.sets) == 1
        assert sample_match.sets[0].numero == 1

    def test_match_code_obligatoire(self):
        with pytest.raises(ValidationError):
            Match(equipe_a=Equipe(nom="A", joueurs=[], liberos=[]),
                  equipe_b=Equipe(nom="B", joueurs=[], liberos=[]))
